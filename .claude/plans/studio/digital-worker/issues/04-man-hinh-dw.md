# 04 — Màn hình Digital Worker, hàng đợi việc và thẻ duyệt

Status: resolved
Blocked by: 03
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R9.4, R9.5, DWK21

## Mục tiêu

Business Owner, Validator và người làm việc thấy DW, hàng đợi chung, gói bàn giao và thẻ duyệt trên
web, bằng Ant Design v6 (R9).

## Việc cần làm

1. Client sinh từ OpenAPI cho các route của ticket 01-03 và `trail` của wf-lite/02
   (`apps/web/lib/api`), không gõ tay kiểu.
2. `apps/web/app/digital-workers/page.tsx`: bảng antd (tên, trạng thái `Tag`, mandate rút gọn, số việc
   đang mở).
3. `apps/web/app/digital-workers/[id]/page.tsx`: `Descriptions` hồ sơ và bốn người, bảng loại quyết
   định (trần, đã kiếm, hiệu lực hiện bằng `Tag` "Tự động", "Hỏi" hay "Chặn" kèm mức A0-A4), `Statistic` của scorecard 30 ngày, cây quy trình chỉ đọc vẽ bằng
   antd (`Steps` dọc, lane của `logic.switch` và `human.approval` lồng trong `Card`) từ tài liệu đã ghim.
4. `apps/web/app/work/page.tsx`: hàng đợi chung, lọc trạng thái và loại người giữ, `Drawer` của một
   việc với `trail` và gói bàn giao.
5. `apps/web/app/approvals`: thẻ cho `dw.decision` (tên DW, loại quyết định, mức hiệu lực, đề xuất:
   tiêu đề và thân thư), với ba nút Duyệt, "Sửa rồi duyệt" (form từ `proposal_schema`) và "Từ chối" bắt
   buộc lý do.
6. Mục "Digital Worker" và "Hàng đợi việc" trong thanh trên cùng của `@dw/ui`; ngày giờ qua `lib/dates.ts`.
7. Trạng thái 403 và 404 dùng chung của app (R9.5).
8. Test vitest cho mỗi trang (dữ liệu giả của API) và DWK21.

## Tiêu chí chấp nhận

- [x] R9.1: trang liệt kê hiện đủ bốn cột với dữ liệu giả hai DW.
- [x] R9.2: trang hồ sơ hiện bốn người, ba mức của mỗi loại quyết định với chữ Tự động/Hỏi/Chặn, bốn số scorecard và mọi bước của tài liệu.
- [x] R9.3: lọc `handed_off` chỉ hiện việc đó; `Drawer` hiện bốn trường gói và `trail`.
- [x] R9.4: approval `dw.decision` hiện tiêu đề thư đề xuất và mức hiệu lực.
- [x] R9.5 (DWK21): API giả trả 403 → không có hàng dữ liệu nào, hiện trạng thái không có quyền.
- [x] Xong: `pnpm --filter web test` xanh.

## Nguồn

- `apps/web/app/approvals`; `CLAUDE.md` mục Web UI; spec: R9, DWK21.

## Comments

- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-31 (agent): resolved (`a205deb` hai route đọc, `f22e452` màn hình, `2e09dc8` sửa sau khi xem trên trình duyệt).
  - Khác ticket, quyết khi spec im lặng (agent, theo ủy quyền 31/10/2026):
    - API chưa có hai thứ màn hình cần, nên thêm: `open_items` trên mỗi DW của `GET /digital-workers`
      (`WorkQueue.open_counts`, một câu đếm theo nhóm dưới RLS, việc chưa `done`/`failed`/`cancelled`, kể cả đã
      bàn giao) và `GET /digital-workers/{id}/workflow` (cây bước của tài liệu đã ghim qua sổ loại bước mà bộ
      biên dịch đọc, mỗi loại quyết định với mức hiệu lực và `mode` `auto`/`ask`/`blocked`). Mức và "Hỏi" lấy từ
      `DecisionAutonomy.class_autonomy`, cùng một lần đọc với cổng, web không tự suy (failure-modes #2). "Chặn"
      theo spec mục R9: mọi công cụ mà bước `tool.call` của loại đó gọi đều ngoài `allowed_tools` (so tên, bỏ
      `@phiên bản`). Pin không còn trong gói: 404 `workflow_not_shipped`. Nếu sai thì: bỏ `open_items` và route
      `/workflow`, web đọc `GET /work-items` và tài liệu theo cách khác.
    - Kiểu DW trong `@dw/api-client` là kiểu sinh từ OpenAPI (`components["schemas"][...]`), không mirror zod
      viết tay như các route cũ; kiểm lúc chạy chỉ là "là object". Nếu sai thì: thêm schema zod vào
      `@dw/contracts` với `SameType` như `SodRuleView`.
    - Thẻ `dw.decision` là một mục trong bảng `CARDS` của `/approvals` theo `approval_type`, không nhánh trong
      vòng lặp. Nút theo `can_decide` của server. "Từ chối" cần lý do ở web (spec D18); server không đòi vì
      `requires_comment` của loại này là false. Trường thư xếp theo `required` của schema vì jsonb sắp lại khóa
      object. Nếu sai thì: bật `requires_comment` cho `dw.decision` để server cũng đòi.
    - Bộ lọc và việc đang mở của `/work` nằm trên URL (`?status=&holder=&item=`), gửi link được. Drawer ở bên
      phải từ `lg`, ở dưới khi hẹp hơn.
    - Chi phí model hiện bằng `formatUsd` mới trong `lib/money.ts` (dấu phẩy thập phân, "USD").
  - Test: vitest 10 ca (R9.1-R9.5, DWK21, khóa nút, lý do từ chối, sửa rồi duyệt giữ trường khóa, thứ tự trường);
    unit API 3 ca, unit `wflite/outline` 6 ca, unit `class_autonomy` 6 ca, integration `open_counts` 1 ca.
  - Mutation: `mutations/04.yaml` 13/13 đỏ, đối chứng xanh. Phần web (runner không chạy vitest) đột biến tay 8/8 đỏ:
    trang hồ sơ hiện dữ liệu sau 403, danh sách vẫn vẽ bảng sau 403, từ chối không lý do, nút mở cho người server
    không cho, trường khóa sửa được, bộ lọc không gửi, nhãn chế độ là mã, thứ tự trường theo jsonb. Hai đột biến đầu
    tiên lọt (DWK21 khớp câu của toast; một đột biến không đổi gì vì antd đã gửi giá trị trường bị khóa) nên đã
    sửa test sang tiêu đề của trạng thái chung và đổi đột biến.
  - `reviewing-feature-security`: tenant (đếm dưới `tenant_session` cộng workspace rõ, tenant B nhận `{}`; route
    `/workflow` qua `DigitalWorkerService.get`; cache web theo workspace); phân quyền (`open_counts` đòi `dw.read`,
    `/workflow` 404 khi không có, nút thẻ theo `can_decide`, server vẫn quyết ở ticket 02); tự chủ (chỉ đọc; mức
    không đọc được là A0 và "Hỏi"); nội dung không tin (đề xuất in dạng chữ React); audit (không ghi gì); vòng đời
    (không tạo gì mới). Không đổi phụ thuộc hay ảnh.
  - Giao diện (Playwright trên app thật, API :8010 và web :3040 với DB nháp `dw_ui04`, seed demo cộng một DW
    chăm sóc lead; Playwright MCP không có trong phiên này nên chạy Playwright của repo): sáng và tối, 1280 và 768
    px, năm trang; không lỗi trang, không cuộn ngang. Sửa sau khi xem: nhiệm vụ dài đẩy cột "Việc đang mở" ra ngoài
    (bảng giờ rộng cố định nên ellipsis cắt), tiêu đề bước màu phụ của antd "wait" (giờ màu chữ), trường đề xuất
    theo thứ tự jsonb. Dưới 992px bảng cuộn trong khung của nó. Ảnh: `docs/demo/digital-worker/04-screens/`.
    Chưa đo tương phản bằng số; mọi màu đi qua theme và Tag preset của `@dw/ui`.
  - Độ trễ (200 lời gọi ấm sau 20 lời gọi khởi động, uvicorn thật, PostgreSQL thật; hai DW, 6.000 việc trong 120
    ngày, một phần năm còn mở; hai lượt, số của lượt hai): `GET /digital-workers` cha `a793c03` P50/P95/P99
    34,1/46,5/56,2 ms, sau 49,4/60,1/70,8 ms; `GET /digital-workers/{id}/workflow` (route mới) 55,6/70,5/88,5 ms.
    P95 của danh sách xấu hơn cha 29%: lý do là một giao dịch nữa dưới RLS cho câu đếm (thực thi 3,3 ms theo
    `EXPLAIN ANALYZE`, phần còn lại là vòng mở phiên và `set_config` qua Docker Desktop). Trong ngân sách 300 ms nên
    giữ; gộp câu đếm vào câu liệt kê DW sẽ buộc repository DW đọc bảng của hàng đợi. Nếu sai thì: một câu
    `LEFT JOIN LATERAL` trong `SqlDigitalWorkerRepository.list`.
  - Cổng: ruff, format, mypy, `make test-unit` (1781), `test-contract` (24, snapshot OpenAPI và kiểu TS sinh lại),
    `test-architecture`; integration của `dw_platform`, `dw_agent_runtime`, `apps/api` xanh (3 skip);
    `pnpm --filter web test` 22 tệp xanh, `tsc`, `next lint`.
