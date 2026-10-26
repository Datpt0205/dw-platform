# 01 — Thăm dò Đề nghị mua hàng trong CI, danh sách chỗ hụt và chốt chặn mkt\_

Status: needs-triage
Blocked by: .claude/plans/studio/marketing-pilot/issues/02-gieo-to-chuc-va-object-qua-api.md, .claude/plans/studio/agent-lifecycle/issues/06-cong-chat-luong-va-ca-kich-ban.md, .claude/plans/studio/workflow-nodes/issues/06-tool-call-va-human-approval.md, .claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, R2.2, R2.3, R2.4, R3.1, R3.2, PRB1, PRB2, PRB3, PRB4

## Mục tiêu

Người giữ nền tảng có một test CI dựng miền Đề nghị mua hàng chỉ qua API công khai với nguyên liệu W1, một danh sách chỗ
hụt mà CI giữ đúng, và một chốt chặn làm `make ci` đỏ khi mã nền tảng mang literal của gói Marketing hay của thăm dò
(spec R1, R2, R3; YC111; V4.39). Phần W2 (dòng hàng, tham chiếu, email cho nhà cung cấp, HTTP tới ERP giả) là các dòng
Ngoài phạm vi của spec.

## Việc cần làm

1. `tests/e2e/domain_probe/seed.py`, dùng cùng client HTTP với harness của marketing-pilot/02
   (`tests/e2e/marketing_pilot/`), chỉ gọi route công khai, không SQL, không adapter, không migration (spec R1.1):
    - công ty C (thăm dò) tạo qua `POST /api/v1/platform/tenants` với hai chủ sở hữu, như marketing-pilot/02 tạo công ty
      của nó (YC114; V4.38); một workspace Mua hàng dưới workspace gốc;
    - hai đối tượng qua `POST /api/v1/studio/artifacts` (kind `object`), `PUT .../draft` và route gửi, phát hành qua
      người thứ hai như marketing-pilot/02 bước 2: `prq_supplier` (`name` `text`, `email` `email`, `tax_code` `text`) và
      `prq_request` (`title` `text`, `amount` `number`, `cost_center` `picklist`, `status` `picklist` với `draft`,
      `approved`, `rejected`), mọi trường có `pd_category`, kiểu trong danh sách của custom-objects:R2.1;
    - vai Người đề nghị (đọc, tạo `prq_request` mức Của tôi) và Tài chính (đọc `prq_request` mức Toàn công ty), qua API
      quản trị vai với đề xuất của chủ thứ nhất và duyệt của chủ thứ hai; một tài khoản dịch vụ đọc và sửa `prq_request`;
    - một quy trình `prq_approval`: trình kích hoạt chạy tay; `logic.switch` theo `amount` (dưới 20.000.000 thì một Bước
      `human.approval@1` cho trưởng phòng; từ 20.000.000 trở lên thì hai Bước nối tiếp, trưởng phòng rồi Tài chính, người
      duyệt nêu theo id với `assignee_kind` `user`); `data.object.update` ghi `status` theo quyết định; ba ca kịch bản tất
      định (dưới ngưỡng duyệt, trên ngưỡng duyệt cả hai cấp, bị từ chối ở cấp đầu) gắn với thành phần quy trình trong kho ca
      của agent-lifecycle (YC115); gửi phát hành và người thứ hai duyệt.
2. `pyproject.toml` gốc: ràng buộc độc lập import-linter `domain_probe_independence` cấm `tests/e2e/domain_probe/*`
   import bất kỳ `dw_*.adapters*` hay nội bộ nền tảng, như `marketing_pilot_independence` (spec R1.2, PRB1).
3. `tests/e2e/domain_probe/test_probe.py`, marker `e2e`, chạy ở bước "E2E tests" của CI
   (`.github/workflows/ci.yml:250-253`): chạy `seed.py`; khẳng định Cổng chất lượng đã chạy ba ca và phiên bản Đang dùng
   (spec R1.3); chạy tay hai Đề nghị mua (15.000.000 và 50.000.000) qua `POST /api/v1/studio/workflows/{artifact_id}/runs`
   và quyết các Bước phê duyệt qua route quyết định của phê duyệt, khẳng định nhánh, số Bước phê duyệt và `status` cuối
   (spec R1.4); khi chạy cùng stack với công ty thí điểm của marketing-pilot/02, một thành viên của công ty C `GET`,
   `PATCH` một bản ghi `mkt_lead` của công ty thí điểm theo id và đọc danh sách (spec R1.5, PRB2).
4. Danh sách chỗ hụt (spec R2): mỗi bước của miền mà nguyên liệu W1 không làm được là một mục `id`, `step`, `reason`,
   `workaround` (hay `null`), `wave` (`W2` hay `W3`); test ghi danh sách của lần chạy ra
   `tests/e2e/domain_probe/.out/gaps.json` (thư mục bỏ qua trong `.gitignore`) và so hai chiều với
   `tests/e2e/domain_probe/expected_gaps.yaml`, nêu mục thừa và mục thiếu. Danh sách mong đợi đầu tiên gồm ít nhất: dòng
   hàng và tổng tiền (chủ–chi tiết, W2), tham chiếu tới Nhà cung cấp và Trung tâm chi phí (lookup, W2; vá tạm: id và tên
   chép vào trường `text`), email đơn đặt hàng cho nhà cung cấp (luật `transactional`, YC112, W2), kiểm ngân sách và tạo
   đơn ở ERP (`http.request`, W2), người duyệt theo trung tâm chi phí (vá tạm: id người duyệt nêu thẳng trong cấu hình Bước),
   đính kèm báo giá (W3; vá tạm: trường `text` chứa URL) và báo cáo chi theo trung tâm chi phí (W3). Một mục chỉ vào danh
   sách sau khi script thử bước đó và thấy nó không làm được; mục nào không thử được thì ghi `reason` là chưa thử và
   Comments nêu vì sao.
5. `scripts/verify_architecture.py`: `check_pack_literals()` gọi từ `main()`, đọc cây dưới `--root` (tham số của
   studio-skeleton/01): mọi tệp `.py`, `.ts`, `.tsx`, `.sql`, `.yaml` dưới `packages/` và `apps/`, trừ thư mục `tests/`,
   `__tests__/` và tệp `*.test.ts`, chứa `mkt_` hay `prq_` → một dòng nêu tệp, số dòng và chuỗi, thoát 1 (spec R3.1,
   R2.4). `scripts/test_verify_architecture.sh` thêm hai ca trồng lỗi: cây thử có `packages/python/dw_probe/src/x.py`
   chứa `"mkt_lead"`, rồi `"prq_request"`; mỗi ca đòi thoát 1 với dòng nêu tệp; một tệp `tests/` chứa `mkt_lead` trong cây
   thử vẫn xanh. Trên checkout kiểm tra xanh (spec R3.2).
6. Ticket này không sửa tệp nào dưới `packages/` hay `apps/` (spec R2.4); `git diff --stat` của thay đổi chỉ có
   `tests/e2e/domain_probe/`, `pyproject.toml`, `.gitignore` và hai tệp ở `scripts/`, ghi vào Comments khi đóng.

## Tiêu chí chấp nhận

- [ ] R1.1 (PRB1): `seed.py` dựng công ty C với hai chủ sở hữu, hai đối tượng Đang dùng, hai vai, một tài khoản dịch vụ
      và quy trình `prq_approval` Đang dùng, chỉ bằng lời gọi HTTP tới route công khai; không lời gọi nào chạm database
      trực tiếp.
- [ ] R1.2 (PRB1): thêm một `import` adapter vào `tests/e2e/domain_probe/` → `lint-imports` đỏ; gỡ ràng buộc
      `domain_probe_independence` → import lọt, ca đó đỏ.
- [ ] R1.3: lần gửi phát hành của `prq_approval` có Lượt kiểm định chạy đúng ba ca kịch bản, mọi ca qua; đổi `outcome`
      mong đợi của ca bị từ chối → cổng trượt, phiên bản không lên Đang dùng.
- [ ] R1.4: Đề nghị 15.000.000 mở đúng một Bước phê duyệt, duyệt → `status` `approved`; Đề nghị 50.000.000 mở hai Bước
      nối tiếp, Bước thứ hai chỉ mở sau quyết định của Bước thứ nhất; từ chối ở cấp đầu → `status` `rejected`, không Bước
      thứ hai.
- [ ] R1.5 (PRB2): thành viên công ty C `GET` và `PATCH` một bản ghi `mkt_lead` của công ty thí điểm theo id → 404, bản
      ghi không đổi; đọc danh sách `mkt_lead` → 0 dòng của công ty thí điểm.
- [ ] R2.1: bước "E2E tests" của CI chạy `test_probe.py` (có trong danh sách test đã chạy của job) và để lại
      `gaps.json`.
- [ ] R2.2: mọi mục của `gaps.json` có đủ `id`, `step`, `reason`, `workaround`, `wave`; một mục thiếu `wave` → test đỏ.
- [ ] R2.3 (PRB3): xóa một mục khỏi `expected_gaps.yaml` → test đỏ, nêu mục thừa của lần chạy; thêm một mục mà lần chạy
      làm được → test đỏ, nêu mục thiếu; đổi phép so thành một chiều → một trong hai ca lọt.
- [ ] R2.4 (PRB4): `check_pack_literals()` xanh trên checkout sau thay đổi, nên không tệp mã nền tảng nào mang `prq_`;
      `git diff --stat` ghi ở Comments không có đường dẫn dưới `packages/` hay `apps/`.
- [ ] R3.1 (PRB4): cây thử có `packages/python/dw_probe/src/x.py` chứa `"mkt_lead"` → kiểm tra thoát 1 nêu tệp và dòng;
      cùng ca với `"prq_request"` → thoát 1; tệp `tests/` chứa `mkt_lead` → xanh; gỡ lời gọi `check_pack_literals()` khỏi
      `main()` → hai ca trồng lỗi đỏ.
- [ ] R3.2: `make test-architecture` chạy `check_pack_literals()` và xanh trên checkout.
- [ ] Xong: `make ci && make test-e2e` xanh.

## Nguồn

- `.claude/plans/studio/marketing-pilot/spec.md:12`; spec: R3.1 (bằng chứng hôm nay chỉ là một lần grep).
- `scripts/verify_architecture.py:135-158`, `Makefile:98-101`; spec: R3.1, R3.2.
- `.github/workflows/ci.yml:250-253`, `pyproject.toml:194`; spec: R2.1.
- `docs/adr/0100-studio-is-platform-code-in-this-repository.md:40`; spec: R3; YC111, YC112, YC114, YC115.

## Comments

- 2026-10-26 (agent): ticket mới của lượt h theo V4.39 và H-16 (mục C: đường dẫn và dòng Blocked by cố định).
  workflow-engine/08 đứng trong Blocked by để thăm dò chạy trên lõi W1 đủ (cổng E1), nên danh sách chỗ hụt không ghi một
  hụt mà lõi W1 đã đóng; workflow-nodes/06 cho `human.approval@1`; agent-lifecycle/06 cho ca kịch bản ở cổng;
  marketing-pilot/02 cho harness và client HTTP dùng chung.
