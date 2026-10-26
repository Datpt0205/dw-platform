# Thăm dò miền thứ hai: Đề nghị mua hàng trong CI

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 26/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio hứa là nền tảng trung lập, không mang miền Marketing trong mã, nhưng đến nay chỉ một miền được dựng trên nó và
bằng chứng duy nhất là một lần grep lúc viết spec. Lát này dựng một miền thứ hai, Đề nghị mua hàng, chỉ bằng một script
gieo qua API công khai, chạy trong CI từ W1 với nguyên liệu W1, xuất một danh sách chỗ hụt, và thêm một chốt chặn làm
CI đỏ khi mã nền tảng mang một chuỗi `mkt_` của gói Marketing (YC111; V4.39; H-16). Lối ra của W1 là 0 dòng mã nền tảng
riêng cho miền đó và một danh sách chỗ hụt được kiểm hai chiều.

## Hiện trạng (đã kiểm ở `01167ff` ngày 26/10/2026)

- Miền Marketing của lát thí điểm dựng chỉ qua API công khai, và bằng chứng "nền tảng không mang Marketing" là một lần
  grep `mkt_lead` trên `packages`, `apps` lúc viết spec (`.claude/plans/studio/marketing-pilot/spec.md:12`). Thiếu:
  không test nào giữ điều đó sau ngày viết.
- ADR-0100 (Accepted) quyết 1 nói Studio là năng lực nền tảng, không phải một context hay một sản phẩm
  (`docs/adr/0100-studio-is-platform-code-in-this-repository.md:40`). Thiếu: quyết định đó chưa có test.
- `make ci` chạy `test-architecture`, gồm `scripts/verify_architecture.py` (`Makefile:98-101`, `Makefile:157`), mà
  `main()` gọi từng kiểm tra (`scripts/verify_architecture.py:135-158`). Ràng buộc: chốt chặn `mkt_` vào đó, cạnh kiểm
  tra đăng ký mà studio-skeleton/01 thêm cùng tham số `--root` và test trồng lỗi.
- CI chạy `pytest -m e2e` trong job tích hợp (`.github/workflows/ci.yml:250-253`), với marker `e2e` khai ở
  `pyproject.toml:194`. Ràng buộc: thăm dò là một test `e2e`, như harness của lát thí điểm.
- Chưa có thư mục `tests/e2e/`; thư mục `tests/` gốc chỉ có `tests/support/pg_test_db.py`
  (`tests/support/pg_test_db.py:1`). Ràng buộc: harness của thăm dò và của lát thí điểm cùng dạng, mỗi bên một thư mục.

## Mục tiêu

### R1 — Đề nghị mua hàng dựng chỉ qua API công khai, với nguyên liệu W1

Người giữ nền tảng có bằng chứng chạy được rằng một miền khác Marketing dựng được mà không thêm mã nền tảng (YC111).

- R1.1 KHI script gieo của thăm dò chạy, script PHẢI dựng một công ty với hai chủ sở hữu, đối tượng Nhà cung cấp và Đề
  nghị mua, vai Người đề nghị (mức Của tôi) và Tài chính (mức Toàn công ty), một tài khoản dịch vụ và một quy trình duyệt
  theo ngưỡng số tiền, chỉ bằng lời gọi HTTP tới route công khai của Studio, như script gieo của marketing-pilot/02.
- R1.2 NẾU một tệp của harness thăm dò import một adapter hay nội bộ nền tảng (`dw_*.adapters*`), THÌ `lint-imports`
  PHẢI đỏ.
- R1.3 KHI quy trình của thăm dò được gửi phát hành, Cổng chất lượng PHẢI chạy các ca kịch bản tất định của miền (dưới
  ngưỡng một cấp duyệt, trên ngưỡng hai cấp duyệt nối tiếp, bị từ chối ở cấp đầu) và phiên bản chỉ lên Đang dùng khi
  mọi ca qua và người thứ hai duyệt (agent-lifecycle/06, YC115).
- R1.4 KHI một Đề nghị mua được chạy tay qua route chạy của quy trình, lượt chạy PHẢI đi đúng nhánh theo số tiền, mở
  đúng số Bước phê duyệt nối tiếp, và kết thúc với trạng thái của bản ghi Đề nghị mua đúng quyết định.
- R1.5 NẾU một thành viên của công ty thăm dò đọc hay ghi bản ghi `mkt_lead` của công ty thí điểm Marketing chạy cùng
  deployment, THÌ API PHẢI trả 404 và không đổi gì.

### R2 — Thăm dò chạy trong CI và xuất danh sách chỗ hụt

Người lập kế hoạch đọc được miền thứ hai còn hụt gì ở mỗi đợt, từ một danh sách mà CI giữ đúng (YC111; V4.39).

- R2.1 KHI job tích hợp của CI chạy `pytest -m e2e`, test thăm dò PHẢI chạy script gieo của R1 trên stack của job và
  ghi danh sách chỗ hụt ra một tệp kết quả của lần chạy.
- R2.2 Mỗi mục của danh sách chỗ hụt PHẢI nêu bước của miền, vì sao nguyên liệu W1 không làm được, cách vá tạm nếu có, và
  đợt dự kiến mở (W2 hay W3).
- R2.3 NẾU danh sách chỗ hụt của lần chạy khác danh sách mong đợi ghi trong repo (một chỗ hụt mới, hay một chỗ hụt
  trong danh sách mà lần chạy làm được), THÌ test thăm dò PHẢI đỏ và nêu mục khác nhau.
- R2.4 Thay đổi thêm thăm dò PHẢI không thêm dòng nào dưới `packages/` hay `apps/` riêng cho miền Đề nghị mua hàng; tiền
  tố đối tượng của thăm dò, `prq_`, không xuất hiện trong mã nền tảng.

### R3 — Chốt chặn chuỗi `mkt_` trong mã nền tảng

Mã nền tảng không bao giờ mang tên của một gói, nên một literal của gói Marketing làm CI đỏ trước khi gộp
(ADR-0100 (Accepted) quyết 1; V4.39).

- R3.1 NẾU một tệp mã dưới `packages/` hay `apps/`, ngoài thư mục test, chứa chuỗi `mkt_` hay chuỗi `prq_`, THÌ
  `scripts/verify_architecture.py` PHẢI thoát 1 và in một dòng nêu tệp, dòng và chuỗi đó.
- R3.2 KHI `make ci` chạy trên checkout, chốt chặn của R3.1 PHẢI chạy trong `test-architecture` và xanh.

## Trong phạm vi

- Harness `tests/e2e/domain_probe/` (`seed.py`, `test_probe.py`), danh sách chỗ hụt mong đợi
  `tests/e2e/domain_probe/expected_gaps.yaml` và tệp kết quả của lần chạy.
- Ràng buộc độc lập import-linter `domain_probe_independence` trong `pyproject.toml` gốc.
- Kiểm tra `check_pack_literals()` trong `scripts/verify_architecture.py` và các ca trồng lỗi của nó trong
  `scripts/test_verify_architecture.sh`.

## Ngoài phạm vi

| Việc                                                                              | Vì sao                                                                                                                                                               | Chủ                                         |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| W2: dòng hàng của Đề nghị mua (chủ–chi tiết) và tổng tiền                         | chủ–chi tiết là W2 của custom-objects; ở W1 là một chỗ hụt của danh sách (V4.39)                                                                                     | domain-probe; custom-objects, đợt sau (W2)  |
| W2: tham chiếu từ Đề nghị mua tới Nhà cung cấp và tới Trung tâm chi phí           | lookup là W2 của custom-objects; ở W1 là một chỗ hụt (V4.39)                                                                                                         | domain-probe; custom-objects, đợt sau (W2)  |
| W2: email đơn đặt hàng cho nhà cung cấp qua luật `transactional` dưới Sàn gửi tin | YC112; luật có sau ý kiến luật sư (compliance-pdpl/02); ở W1 mọi tin tới người ngoài thành viên đi qua sàn tiếp thị và đơn bị chặn, nên thăm dò W1 không gửi (V4.39) | domain-probe; compliance-pdpl, đợt sau (W2) |
| W2: lời gọi HTTP tới một ERP giả để kiểm ngân sách và tạo đơn                     | `http.request` là W2 của workflow-nodes, sau proxy ra ngoài; ở W1 là một chỗ hụt (V4.39)                                                                             | domain-probe; workflow-nodes, đợt sau (W2)  |
| Gói Mua hàng (cấu hình đóng gói, cài một lần)                                     | thăm dò chứng minh nền tảng, không ra sản phẩm; gói sau Marketing chưa có đợt                                                                                        | không làm                                   |

## Kiểm soát

| #    | Kiểm soát                                               | Yêu cầu    | Test âm                                                                                                                                                                                                        |
| ---- | ------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PRB1 | Thăm dò chỉ dựng qua API công khai                      | R1.1, R1.2 | Thêm một `import` adapter vào `tests/e2e/domain_probe/` → `lint-imports` đỏ; gỡ ràng buộc `domain_probe_independence` → import lọt, ca trồng lỗi đỏ                                                            |
| PRB2 | Công ty thăm dò không chạm dữ liệu của công ty thí điểm | R1.5       | Thành viên công ty thăm dò `GET` và `PATCH` một bản ghi `mkt_lead` của công ty thí điểm theo id → 404, bản ghi không đổi; đọc danh sách → 0 dòng của công ty thí điểm                                          |
| PRB3 | Danh sách chỗ hụt được kiểm hai chiều                   | R2.3       | Xóa một mục khỏi `expected_gaps.yaml` → test đỏ, nêu mục thừa của lần chạy; thêm một mục mà lần chạy làm được → test đỏ, nêu mục thiếu; đổi phép so thành chỉ một chiều → một trong hai ca lọt                 |
| PRB4 | Mã nền tảng không mang literal của gói                  | R3.1, R2.4 | Cây thử có `packages/python/dw_probe/src/x.py` chứa `"mkt_lead"` → kiểm tra thoát 1 nêu tệp và dòng; cùng ca với `"prq_request"` → thoát 1; gỡ lời gọi `check_pack_literals()` khỏi `main()` → ca trồng lỗi đỏ |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của ticket).
- `make ci` xanh với chốt chặn của R3; `make test-e2e` xanh trên stack đủ, và bước "E2E tests" của CI chạy test thăm dò.
- `.claude/plans/studio.md` ghi lát W1 của thăm dò đã xong và dẫn danh sách chỗ hụt.

## Phụ thuộc

- marketing-pilot: mẫu script gieo chỉ qua API công khai và ràng buộc độc lập của harness (marketing-pilot:R1.1,
  marketing-pilot:R1.2; `.claude/plans/studio/marketing-pilot/issues/02-gieo-to-chuc-va-object-qua-api.md`), gồm tạo công
  ty với hai chủ sở hữu (YC114; V4.38).
- agent-lifecycle: Cổng chất lượng với ca kịch bản tất định của quy trình (YC115;
  `.claude/plans/studio/agent-lifecycle/issues/06-cong-chat-luong-va-ca-kich-ban.md`).
- workflow-nodes: Bước `human.approval@1` với người duyệt `assignee_kind` `user`
  (`.claude/plans/studio/workflow-nodes/issues/06-tool-call-va-human-approval.md`); `logic.switch` và Bước dữ liệu đối
  tượng có trước nó.
- workflow-engine: lõi W1 đủ, gồm điểm chờ `outcome_review` (cổng E1;
  `.claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md`), để danh sách chỗ hụt không ghi một hụt
  mà lõi W1 đã đóng.
- workflow-triggers: route chạy tay `POST /api/v1/studio/workflows/{artifact_id}/runs` (workflow-triggers:R2.1).
- studio-skeleton: tham số `--root` của `scripts/verify_architecture.py` và `scripts/test_verify_architecture.sh` (ticket
  01 của spec đó), nơi chốt chặn của R3 thêm ca trồng lỗi.
- Kiểm lại khi: marketing-pilot/02 đổi harness hay cách tạo công ty → R1.1, ticket 01; một spec mở ở W1 một nguyên liệu có
  trong danh sách chỗ hụt → `expected_gaps.yaml` (test của R2.3 đỏ cho tới khi mục đó bỏ); YC112, chủ–chi tiết, lookup
  hay `http.request` mở → các dòng W2 của Ngoài phạm vi; gói Marketing đổi tiền tố → R3.1.

## Câu hỏi còn mở

## Quyết định

- 25/10/2026 (Đạt): V4.39: thăm dò Đề nghị mua hàng bằng script gieo qua API công khai, chạy trong CI; ở W1 chỉ dùng
  nguyên liệu W1, ở W2 thêm dòng hàng, tham chiếu, email cho nhà cung cấp và HTTP tới ERP giả; lối ra là 0 dòng mã nền
  tảng riêng cho miền đó và một danh sách chỗ hụt; một chốt chặn quét chuỗi `mkt_` trong `packages/` và `apps/` chuyển đỏ
  khi có người gieo một literal; luật `transactional` dưới Sàn gửi tin ở W2, sau ý kiến luật sư (YC111, YC112). Sửa:
  spec mới, R1, R2, R3, Ngoài phạm vi, ticket 01.
- 25/10/2026 (agent, tạm): H-16: một spec nhỏ `.claude/plans/studio/domain-probe/spec.md` với tiền tố kiểm soát `PRB` và
  ticket 01 ở W1; phần W2 là dòng Ngoài phạm vi có đợt và chủ; script gieo chỉ gọi API công khai như marketing-pilot/02;
  chốt chặn `mkt_` chạy trong `make ci`. Sửa: spec mới, ticket 01. Nếu sai thì: ticket thăm dò ở marketing-pilot.
- 26/10/2026 (agent, tạm): chốt chặn của R3 quét tệp mã dưới `packages/` và `apps/` trừ thư mục test (`tests/`,
  `__tests__/`, `*.test.ts`), vì test của nền tảng được dùng tên đối tượng thí điểm làm dữ liệu thử còn mã chạy thì không;
  nó quét cả `prq_`, tiền tố của thăm dò, để R2.4 có một phép kiểm chứ không chỉ là lời hứa; danh sách chỗ hụt mong đợi
  nằm trong repo và được so hai chiều, để danh sách không cũ đi lặng lẽ (`failure-modes.md` #2). Sửa: R2.3, R2.4, R3.1,
  PRB3, PRB4. Nếu sai thì: chốt chặn quét cả thư mục test, và danh sách chỗ hụt chỉ là tệp kết quả của CI, không có bản
  mong đợi.

## Danh sách ticket

| #   | Ticket                                                                                         |
| --- | ---------------------------------------------------------------------------------------------- |
| 01  | [Thăm dò Đề nghị mua hàng trong CI và chốt chặn mkt\_](issues/01-de-nghi-mua-hang-trong-ci.md) |
