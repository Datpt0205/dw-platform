# 01 — Thăm dò Đề nghị mua hàng trong CI, danh sách chỗ hụt và chốt chặn mkt\_

Status: ready-for-agent
Blocked by: .claude/plans/studio/marketing-pilot/issues/02-gieo-to-chuc-va-object-qua-api.md, .claude/plans/studio/agent-lifecycle/issues/06-cong-chat-luong-va-ca-kich-ban.md, .claude/plans/studio/workflow-nodes/issues/06-tool-call-va-human-approval.md, .claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md, .claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md, .claude/plans/studio/workflow-nodes/issues/04-buoc-du-lieu-doi-tuong-va-giao.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R3.1, R3.2, PRB1, PRB2, PRB3, PRB4, PRB5

## Mục tiêu

Người giữ nền tảng có một test CI dựng miền Đề nghị mua hàng chỉ qua API công khai với nguyên liệu W1, một danh sách chỗ
hụt mà CI giữ đúng, và một chốt chặn làm `make ci` đỏ khi mã nền tảng mang literal của gói Marketing hay của thăm dò
(spec R1, R2, R3; YC111; V4.39). Phần W2 (dòng hàng, tham chiếu, email cho nhà cung cấp, HTTP tới ERP giả) là các dòng
Ngoài phạm vi của spec.

## Việc cần làm

1. `tests/e2e/domain_probe/seed.py` import client HTTP, bộ ký token dev và bộ dựng stack của harness marketing-pilot/02
   (`tests/e2e/marketing_pilot/`), không chép lại, để hai harness có một chủ cho mỗi việc (failure-modes #2); harness đó
   không import `dw_*` nào, nên ràng buộc của bước 2 vẫn giữ. Seed chỉ gọi route công khai, không SQL, không adapter,
   không migration (spec R1.1). Mỗi lần chạy dùng slug có hậu tố ngẫu nhiên, nên chạy lại trên cùng
   stack tạo công ty mới và không đụng công ty cũ; W1 không xóa công ty thăm dò, stack mất cùng volume của nó.
    - Công ty C (thăm dò) và công ty D (đối chứng), mỗi công ty qua `POST /api/v1/platform/tenants` với hai chủ sở hữu, chờ
      `active` như marketing-pilot/02 (YC114; V4.38); mỗi công ty một workspace Mua hàng dưới workspace gốc. Không người
      nào là thành viên của cả hai công ty.
    - Ở C, ba thành viên mời qua `POST /api/v1/admin/invitations`, khác hai chủ sở hữu: Người đề nghị (R), Trưởng phòng
      (M), Tài chính (F). Ở D, một thành viên (Đ) đọc được `prq_request`.
    - Hai đối tượng ở cả C và D qua `POST /api/v1/studio/artifacts` (kind `object`), `PUT .../draft` và route gửi, phát
      hành qua người thứ hai như marketing-pilot/02 bước 2: `prq_supplier` (`name` `text`, `email` `email`, `tax_code`
      `text`) và `prq_request` (`title` `text`, `amount` `number`, `cost_center` `picklist`, `status` `picklist` với
      `draft`, `approved`, `rejected`), mọi trường có `pd_category`, kiểu trong danh sách của custom-objects:R2.1.
    - `status` của `prq_request` đặt dưới bảo mật trường (field-security/01). Vai ở C, qua API quản trị vai
      (tenant-rbac/03, /04) với đề xuất của chủ thứ nhất và duyệt của chủ thứ hai: Người đề nghị (đọc và tạo
      `prq_request` mức Của tôi; `fld.prq_request.status.read`, không `.edit`; quyền chạy tay quy trình `prq_approval`) gán
      cho R; Tài chính (đọc `prq_request` mức Toàn công ty, `fld.prq_request.status.read`, và khóa quyết định mà
      workflow-nodes/06 đóng cho phê duyệt Bước `studio.step.`) gán cho F và M. Một tài khoản dịch vụ (`POST
/api/v1/admin/service-principals`) đọc và sửa `prq_request` mức Toàn công ty, `fld.prq_request.status.edit`, là
      giá trị của điểm gắn `run_as` của `prq_approval` (workflow-triggers/01; tenant-config/05), đề xuất bởi chủ thứ nhất và
      duyệt bởi chủ thứ hai, để mọi lượt, kể cả lượt R chạy tay, chạy và ghi `status` dưới danh tính đó. R tạo bản ghi
      không nêu `status`; giá trị trước quyết định là giá trị mà custom-objects cho trường không nêu, và R1.6 so với giá
      trị đó.
    - Quy trình `prq_approval`: trình kích hoạt chạy tay nhận `record_id`; `logic.switch` theo `amount` tính bằng VND
      (dưới 20.000.000 thì một Bước `human.approval@1` giao M; từ đúng 20.000.000 trở lên thì hai Bước nối tiếp, M rồi F,
      người duyệt nêu theo id với `assignee_kind` `user`); `data.object.update` ghi `status` theo quyết định; ba ca kịch
      bản tất định (dưới ngưỡng duyệt, trên ngưỡng duyệt cả hai cấp, bị từ chối ở cấp đầu) tạo qua
      `POST /api/v1/studio/workflows/{artifact_id}/scenarios` của agent-lifecycle/06 (YC115); gửi phát hành và người thứ
      hai duyệt.
2. `pyproject.toml` gốc: ràng buộc độc lập import-linter `domain_probe_independence` cấm `tests/e2e/domain_probe/*` import
   bất kỳ `dw_*.adapters*` hay nội bộ nền tảng, như `marketing_pilot_independence`, với harness nhập được như một package
   (`__init__.py`) (spec R1.2, PRB1).
3. `tests/e2e/domain_probe/test_probe.py`, marker `e2e`, chạy ở bước "E2E tests" của CI (`.github/workflows/ci.yml:268`):
    - chạy `seed.py`; khẳng định Cổng chất lượng đã chạy ba ca và phiên bản Đang dùng (spec R1.3);
    - R tạo ba Đề nghị mua qua `POST /api/v1/studio/objects/prq_request/records` (15.000.000, đúng 20.000.000 và
      50.000.000) và chạy tay từng cái qua `POST /api/v1/studio/workflows/{artifact_id}/runs`; M và F quyết các Bước qua
      route quyết định của phê duyệt; khẳng định nhánh, số Bước phê duyệt và `status` cuối (spec R1.4);
    - R `PATCH` `status` `approved` trên Đề nghị của chính mình → bị từ chối, `status` giữ `draft`; F quyết Bước thứ nhất
      (giao M) → bị từ chối, Bước vẫn mở (spec R1.6, PRB5);
    - F (mức Toàn công ty ở C, nên mức Của tôi không thể là lý do của 404) `GET`, `PATCH` một bản ghi `prq_request` của D
      theo id → 404, bản ghi không đổi; đọc danh sách `prq_request` → 0 dòng của D; Đ `GET` cùng id → 200 (spec R1.5,
      PRB2).
4. Danh sách chỗ hụt (spec R2): mỗi bước của miền mà nguyên liệu W1 không làm được là một mục `id`, `step`, `reason`,
   `workaround` (hay `null`), `wave` (`W2` hay `W3`) và `probe`: lời gọi công khai thử bước đó cùng mã HTTP và
   `error.code` (hay mã `wf.*`) mà nền tảng trả khi từ chối. Mỗi `probe` khai trong mã của harness
   (`tests/e2e/domain_probe/probes.py`), không trong `expected_gaps.yaml`, nên xóa một mục khỏi tệp mong đợi vẫn để lần
   chạy sinh mục đó. Một `probe` mong 404 chỉ hợp lệ trên một route có tồn tại với id không có, không trên một route
   chưa ai dựng, vì 404 của đường dẫn sai không đo gì. Test chạy mỗi `probe`: đúng mã đã khai → chỗ hụt của lần
   chạy; 2xx → bước đó làm được, mục không vào danh sách của lần chạy; mã khác (5xx, 401, 403, quá hạn) → test đỏ như một
   lỗi, không ghi chỗ hụt (R2.5). Không có mục "chưa thử": bước không thử được bằng một lời gọi thì không vào danh sách
   mà vào Comments. Test ghi danh sách của lần chạy ra `tests/e2e/domain_probe/.out/gaps.json` (thư mục bỏ qua trong
   `.gitignore`), so hai chiều theo cặp (`id`, `wave`) với `tests/e2e/domain_probe/expected_gaps.yaml`, nêu mục thừa và
   mục thiếu; `reason` và `workaround` không so. `.github/workflows/ci.yml` thêm một bước `actions/upload-artifact` (ghim
   theo SHA như các action khác của tệp) giữ `gaps.json` với `if: always()` (R2.6). Danh sách mong đợi đầu tiên gồm ít
   nhất: dòng hàng và tổng tiền (chủ–chi tiết, W2), tham chiếu tới Nhà cung cấp và Trung tâm chi phí (lookup, W2; vá tạm:
   id và tên chép vào trường `text`), email đơn đặt hàng cho nhà cung cấp (luật `transactional`, YC112, W2; thử bằng một Bước gửi tin luật `transactional`
   trong bản Nháp của quy trình, mong lỗi `wf.*` của bộ kiểm), kiểm ngân
   sách và tạo đơn ở ERP (`http.request`, W2), người duyệt theo trung tâm chi phí (`assignee_kind` khác `user`, W2; vá
   tạm: id người duyệt nêu thẳng trong cấu hình Bước), đính kèm báo giá (trường kiểu tệp, W3; vá tạm: trường `text` chứa
   URL). Báo cáo chi theo trung tâm chi phí (W3) không có lời gọi thử nào, nên ghi ở Comments, không vào danh sách.
5. `scripts/verify_architecture.py`: `check_pack_literals()` gọi từ `main()` (`scripts/verify_architecture.py:342`), đọc cây
   dưới `--root` (tham số của studio-skeleton/01): mọi tệp `.py`, `.ts`, `.tsx`, `.js`, `.mjs`, `.sql`, `.yaml`, `.yml`,
   `.json` trên đĩa dưới `packages/`, `apps/` và `db/migrations/`, kể cả chú thích, trừ đường dẫn có một đoạn `tests`,
   `__tests__`, `e2e`, hay một thư mục sinh ra (`node_modules`, `.next`, `dist`, `build`, `.venv`, `__pycache__`), và tệp
   `*.test.*`, `*.spec.*`; chứa `mkt_` hay `prq_` → một dòng nêu tệp, số
   dòng và chuỗi, thoát 1 (spec R3.1, R2.4). Gói `testing/` (như `dw_studio.testing`) không được miễn, vì nó ship cùng
   gói. `scripts/test_verify_architecture.sh` thêm các ca trồng lỗi: cây thử có `packages/python/dw_probe/src/x.py` chứa
   `"mkt_lead"`, rồi `"prq_request"`, rồi `apps/web/lib/x.tsx` chứa `mkt_lead` trong chú thích; mỗi ca đòi thoát 1 với dòng
   nêu tệp; một tệp `tests/` và một tệp `x.test.tsx` chứa `mkt_lead` trong cây thử vẫn xanh. Trên checkout kiểm tra xanh
   (spec R3.2).
6. Ticket này không sửa tệp nào dưới `packages/` hay `apps/` (spec R2.4); `git diff --stat` của thay đổi chỉ có
   `tests/e2e/domain_probe/`, `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml` và hai tệp ở `scripts/`, ghi vào
   Comments khi đóng.

## Tiêu chí chấp nhận

- [ ] R1.1 (PRB1): `seed.py` dựng công ty C và D, mỗi công ty hai chủ sở hữu, ba thành viên R, M, F ở C, hai đối tượng
      Đang dùng, hai vai, một tài khoản dịch vụ ở điểm gắn `run_as` và quy trình `prq_approval` Đang dùng, chỉ bằng lời
      gọi HTTP tới route công khai; không lời gọi nào chạm database trực tiếp; gọi `seed()` hai lần liền trong một lần chạy
      test → hai cặp công ty khác slug, lần thứ hai xanh.
- [ ] R1.2 (PRB1): thêm một `import` adapter vào `tests/e2e/domain_probe/` → `lint-imports` đỏ; gỡ ràng buộc
      `domain_probe_independence` → import lọt, ca đó đỏ.
- [ ] R1.3: lần gửi phát hành của `prq_approval` có Lượt kiểm định chạy đúng ba ca kịch bản, mọi ca qua; đổi `outcome`
      mong đợi của ca bị từ chối → cổng trượt, phiên bản không lên Đang dùng.
- [ ] R1.4: Đề nghị 15.000.000 mở đúng một Bước phê duyệt, duyệt → `status` `approved`; Đề nghị đúng 20.000.000 và
      50.000.000 mở hai Bước nối tiếp, Bước thứ hai chỉ mở sau quyết định của Bước thứ nhất; từ chối ở cấp đầu →
      `status` `rejected`, không Bước thứ hai.
- [ ] R1.5 (PRB2): F của C `GET` và `PATCH` một bản ghi `prq_request` của D theo id → 404, bản ghi không đổi; đọc danh
      sách `prq_request` → 0 dòng của D; Đ `GET` cùng id → 200.
- [ ] R1.6 (PRB5): R `PATCH` `status` `approved` → bị từ chối, `status` giữ giá trị trước lệnh; F quyết Bước thứ nhất
      giao M → bị từ chối, Bước vẫn mở, M quyết sau đó được.
- [ ] R2.1: bước "E2E tests" của CI chạy `test_probe.py` (có trong danh sách test đã chạy của job) và ghi `gaps.json`.
- [ ] R2.6: job CI có artifact `gaps.json`, kể cả ở một lần chạy mà test thăm dò đỏ; bỏ `if: always()` → lần chạy đỏ
      không có artifact.
- [ ] R2.2: mọi mục của `gaps.json` có đủ `id`, `step`, `reason`, `workaround`, `wave`, `probe`; một mục thiếu `wave` →
      test đỏ.
- [ ] R2.3 (PRB3): xóa một mục khỏi `expected_gaps.yaml` → test đỏ, nêu mục thừa của lần chạy; thêm một mục mà lần chạy
      làm được → test đỏ, nêu mục thiếu; đổi `wave` của một mục → test đỏ; đổi phép so thành một chiều → một trong hai ca
      lọt.
- [ ] R2.5: hàm phân loại kết quả `probe` của test (thuần, có test riêng không cần stack) trả "lỗi" cho 500, 401, 403 và
      quá hạn, "chỗ hụt" chỉ cho đúng mã đã khai, "làm được" cho 2xx; đổi nó thành "mọi mã khác 2xx là chỗ hụt" → test đỏ.
- [ ] R2.4 (PRB4): `check_pack_literals()` xanh trên checkout sau thay đổi, nên không tệp mã nền tảng nào mang `prq_`;
      `git diff --stat` ghi ở Comments không có đường dẫn dưới `packages/` hay `apps/`.
- [ ] R3.1 (PRB4): cây thử có `packages/python/dw_probe/src/x.py` chứa `"mkt_lead"` → kiểm tra thoát 1 nêu tệp và dòng;
      cùng ca với `"prq_request"`, và với `mkt_lead` trong chú thích của `apps/web/lib/x.tsx` → thoát 1; tệp `tests/` và
      tệp `x.test.tsx` chứa `mkt_lead` → xanh; gỡ lời gọi `check_pack_literals()` khỏi `main()` → ba ca trồng lỗi đỏ.
- [ ] R3.2: `make test-architecture` chạy `check_pack_literals()` và xanh trên checkout.
- [ ] Xong: `make ci && make test-e2e` xanh.

## Nguồn

- `.claude/plans/studio/marketing-pilot/spec.md:12`; spec: R3.1 (bằng chứng hôm nay chỉ là một lần grep).
- `scripts/verify_architecture.py:342`, `Makefile:99`; spec: R3.1, R3.2.
- `.github/workflows/ci.yml:268`, `pyproject.toml:227`; spec: R2.1.
- `docs/adr/0100-studio-is-platform-code-in-this-repository.md:40`; spec: R3; YC111, YC112, YC114, YC115.

## Comments

- 2026-10-26 (agent): ticket mới của lượt h theo V4.39 và H-16 (mục C: đường dẫn và dòng Blocked by cố định).
  workflow-engine/08 đứng trong Blocked by để thăm dò chạy trên lõi W1 đủ (cổng E1), nên danh sách chỗ hụt không ghi một
  hụt mà lõi W1 đã đóng; workflow-nodes/06 cho `human.approval@1`; agent-lifecycle/06 cho ca kịch bản ở cổng;
  marketing-pilot/02 cho harness và client HTTP dùng chung.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): sửa theo gate `checking-plan-readiness` của spec và ticket (builder check
  và boundary walk; đo trên `c8dab56`). 0 CRITICAL; 9 HIGH, đã sửa hết như khuyến nghị (spec, mục Quyết định ngày
  4/11/2026):
    - (1) PRB2 trên `mkt_lead` của công ty thí điểm không đỏ khi cách ly bản ghi hỏng, vì C không có đối tượng đó, và phụ
      thuộc thứ tự chạy: nay là công ty đối chứng D với cùng `prq_request` và một lần đọc 200 của thành viên D;
    - (2) quy trình duyệt đi vòng được: Người đề nghị tự ghi `status`, người không được giao quyết Bước; thêm R1.6, PRB5;
    - (3) ai là R, M, F, ai tạo bản ghi, ai chạy, tài khoản dịch vụ làm gì: ba thành viên và run-as được nêu;
    - (4) so hai chiều theo gì: cặp (`id`, `wave`);
    - (5) thế nào là "không làm được": mã đã khai; mã khác là lỗi (R2.5), bỏ mục "chưa thử";
    - (6) `gaps.json` mất cùng runner: artifact của job, `ci.yml` vào danh sách tệp;
    - (7) phạm vi chốt chặn: chú thích có tính, `db/migrations/` và các đuôi `.js`, `.mjs`, `.yml`, `.json` vào, miễn
      `e2e/`, `node_modules/`, `*.test.*`, `*.spec.*`, không miễn `testing/`;
    - (8) Blocked by thiếu workflow-triggers/01 (route chạy tay) và workflow-nodes/04 (`data.object.update`);
    - (9) chạy lại trên cùng stack: slug ngẫu nhiên mỗi lần, không xóa ở W1.

    Nếu sai thì: như dòng `Nếu sai thì` của từng ý ở mục Quyết định của spec ngày 4/11/2026.

- 2026-11-04 (agent): MEDIUM để lại, chưa sửa:
    - `amount` âm hay bằng 0 đi nhánh một cấp; W1 có ràng buộc giá trị nhỏ nhất cho trường `number` không là việc của
      custom-objects, và thăm dò ghi một chỗ hụt nếu không có.
    - Chiều ngược của cách ly (thành viên D quyết một Bước của C) chưa có ca; cách ly của phê duyệt có test của
      workflow-nodes/06.
    - Hai quyết định cùng lúc trên một Bước và `Idempotency-Key` phát lại ở route chạy tay có test của workflow-nodes/06
      và workflow-triggers/01, không lặp ở đây.
    - Chốt chặn không bắt literal ghép chuỗi hay chữ hoa (`MKT_`); nó là chốt chặn chống vô ý, không chống cố ý.
    - Lượt xác nhận cùng ngày tìm thêm 7 HIGH, đã sửa: danh tính của lượt chạy tay là tài khoản dịch vụ ở `run_as`;
      `status` dưới bảo mật trường; khóa quyết định cho M và F; F đọc D; `probe` trong mã; báo cáo chi ra Comments, 404
      chỉ trên route có thật; import harness thí điểm thay vì chép; bỏ thư mục sinh ra khỏi vùng quét. Nếu sai thì: lượt
      chạy tay chạy dưới R và R ghi được `status`; `probe` nằm trong `expected_gaps.yaml`.
    - Báo cáo chi theo trung tâm chi phí là chỗ hụt W3 không có lời gọi thử.
    - Mục "người duyệt theo trung tâm chi phí" ghi W2 là ước lượng; spec của workflow-nodes chưa nêu đợt của
      `assignee_kind` khác `user`.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
