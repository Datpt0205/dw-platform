# 02 — Demo chạy thật: một lead đi trọn vòng trên compose, ảnh chụp từng màn

Status: resolved
Blocked by: 01, .claude/plans/studio/digital-worker/issues/04-man-hinh-dw.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, LCP12

## Mục tiêu

Đạt và Business Owner thấy DW chăm sóc lead làm việc thật: docker compose với API, worker, web,
PostgreSQL, Mailpit và model `luna`, một lead đi từ form tới sales, mỗi màn có ảnh chụp (R4, KQ15).

## Việc cần làm

1. `scripts/demo_dw_seed.py`: gieo một tenant demo, năm người (Business Owner, Technical Owner, Work
   Assigner, Validator, sales) với membership và vai, và DW `lead_care` chạy `lead_care@1.0.0` ở
   `operating`, `reply_wait_seconds` 60, `sender_address` `dw-leadcare@demo.local`.
2. `scripts/demo_dw_run.py`: gửi một lead có chữ ký, chờ approval `dw.decision`, kiểm Mailpit chưa có
   thư (R4.4), duyệt bằng Validator qua API, chờ thư tới Mailpit, gửi thư trả lời vào Mailpit qua SMTP,
   chờ việc `handed_off` cho sales, in thời gian mỗi chặng; thoát mã khác 0 ở mọi sai lệch.
3. `make demo-dw`: `docker compose -f infra/compose/docker-compose.yml -f
infra/compose/docker-compose.dev.yml up -d --build` cho postgres, api, worker, web, mailpit với
   model `luna` từ `.env`, migration, seed, rồi script chạy.
4. `apps/web/e2e/demo-digital-worker.spec.ts` (Playwright): đăng nhập dev bằng Business Owner rồi
   Validator, chụp `/digital-workers`, `/digital-workers/[id]`, `/work`, thẻ trên `/approvals`, và
   `Drawer` của việc đã bàn giao, vào `docs/demo/digital-worker/<NN>-<màn>.png`.
5. Ghi đường dẫn ảnh và thời gian các chặng vào `.claude/plans/studio.md` và Comments.

## Tiêu chí chấp nhận

- [x] R4.1: `make demo-dw` dựng đủ năm dịch vụ và một DW `operating`.
- [x] R4.2: lead đi tới `handed_off` cho sales với gói đủ bốn trường, dưới 10 phút không kể chờ người.
- [x] R4.3: năm ảnh có trong `docs/demo/digital-worker/`, mỗi ảnh hiện dữ liệu của lượt demo.
- [x] R4.4 (LCP12): bộ kiểm của script với Mailpit giả đã có thư trước approval → thoát mã khác 0; gỡ phép kiểm thì test đỏ.
- [x] Xong: `make demo-dw` xanh.

## Nguồn

- `./Makefile:122`; `infra/compose/docker-compose.dev.yml:62-87`; spec: R4, LCP12.

## Comments

- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-03 (agent): resolved. `make demo-dw` xanh từ đầu trên stack mới (máy dev, 09:32-09:38 giờ Việt Nam,
  `gpt-5.6-luna`). Thời gian các chặng: dựng compose 242 s (ảnh đã có trong cache), gieo 8 s, lượt lead 108 s, ảnh
  28 s. Trong lượt lead: cửa nhận 202 sau 2,1 s; chấm điểm và soạn thư tới approval `dw.decision` 20,4 s; Validator
  đọc thẻ (ảnh chụp) và duyệt 17,7 s; thư có trong Mailpit ngay khi duyệt (0,0 s, gửi trong lượt resume của API);
  lead trả lời 0,2 s; chờ `reply_wait_seconds` 60 rồi đọc, phân loại `interested` và bàn giao cho sales 65,4 s.
  Tổng 105,9 s, 88,0 s không kể chờ người (R4.2: dưới 600 s). Gói bốn trường: "Lead đã trả lời thư (nhãn:
  interested)." / "Hạng lead: A. Tóm tắt thư trả lời: …" / "Đã chấm điểm, gửi thư đầu tiên sau khi duyệt và đọc thư
  trả lời." / "Liên hệ lead trong hôm nay và tiếp tục trao đổi."
    - Ảnh (R4.3): `docs/demo/digital-worker/01-digital-workers.png`, `02-digital-worker.png`, `03-work.png`,
      `04-approvals-dw-decision.png` (chụp lúc approval còn chờ, trước khi duyệt), `05-work-handed-off.png` (`Drawer`).
    - Cách dựng: `scripts/demo_dw.sh` sau `make demo-dw` (`demo-dw-again`: thêm một lead trên stack đang chạy;
      `demo-dw-down`: dừng và xóa volume). Compose project riêng `dwdemo` = `docker-compose.yml` +
      `docker-compose.dev.yml` + overlay mới `docker-compose.demo.yml`, mọi cổng trên loopback: api 8010, web 3040,
      postgres 25445, valkey 16445, qdrant 16446, s3 19045, Mailpit SMTP 21045 / HTTP 28045. Ảnh của repo đặt tên
      `dw-demo-api:local`, `dw-demo-worker:local`, `dw-demo-web:local` (dạng first-party mà `verify_invariants.py` nhận).
      `dwskel` và mọi container `si-*` không bị đụng.
    - Gieo qua API của nền tảng, không INSERT: người vận hành đăng nhập rồi `scripts/grant_platform_operator.py` (bước
      khởi tạo người vận hành đầu tiên đã có); `POST /platform/tenants` với hai chủ (BO, TO), tenant ở `setup`; hai chủ
      đăng nhập (liên kết lời mời, tenant thành `active`); BO mời Work Assigner (`member`), Validator (`approver`), sales
      (`member`) qua `POST /admin/invitations`, mỗi người đăng nhập (`active`); BO tạo DW với loại quyết định A2/A3;
      TO (người thứ hai, R1.9) đưa DW vào `operating`.
    - Khác với ticket:
        - Đăng nhập dev của năm người không qua `/dev-login`: danh sách ở đó là roster tĩnh `configs/demo/demo_users.yaml`
          với id cố định, còn người của demo do lời mời tạo. Spec Playwright lấy token từ `scripts/issue_dev_token.py`
          (chủ duy nhất của định dạng token) và đặt vào `localStorage` như `/dev-login` làm.
        - Ảnh thẻ `/approvals` phải chụp lúc approval còn chờ (đã quyết thì không còn trong danh sách), nên
          `demo_dw_run` gọi `--at-approval` (phần `@approval` của spec) trước khi kiểm R4.4 và duyệt; bốn ảnh còn lại
          chụp sau khi việc tới sales.
        - `scripts/demo_dw.sh` không `source .env` (`DW_PRODUCT_NAME=Digital Worker` không có ngoặc làm bash dừng); `.env`
          tới script qua `include .env` + `export` của make.
    - LCP12 (R4.4): `require_no_mail_before_approval` là bước ngay trước quyết định; test
      `apps/api/tests/unit/test_demo_dw_run_script.py` (Mailpit giả có thư trước approval: mã khác 0, không gửi quyết
      định) đỏ khi gỡ kiểm (đã thử tay), xanh lại khi trả. Thêm hai test: bàn giao cho người khác sales thì đỏ; ngoài
      khung giờ của Sàn không gửi lead. `mutations/02.yaml` ba mutation, chưa chạy (lượt cuối).
    - `reviewing-feature-security`: không route, migration hay quyền mới; demo đi qua đúng cửa của nền tảng (chữ ký cửa
      nhận, khóa đọc bởi BO có audit `dw.intake_key.read`, Validator duyệt qua API, Sàn gửi tin thật). Sàn không bị nới:
      script kiểm khung 08:00-20:00 giờ Việt Nam bằng `SendFloorPolicy.within_hours` đọc chính tệp chính sách và từ
      chối chạy ngoài khung. `reviewing-deployment-security`: dịch vụ compose chỉ trong overlay demo, cổng loopback, chế
      độ đăng nhập `dev` chỉ ở profile `local`, bí mật thiếu trong `.env` sinh mới mỗi lần chạy và mất theo volume.
    - Cổng: ruff, format, mypy của ba script và test; `test_demo_dw_run_script.py`, `test_compose_invariants.py`;
      `verify_invariants.py`, `verify_architecture.py`, `check_hygiene.py`; web `tsc`, `next lint`, prettier.
    - Xem màn sáng/tối, desktop và 991 px (ảnh xem lại ngoài repo). Chỗ lệch thiết kế, chưa sửa (màn của ticket khác):
      (1) BO và TO hiện bằng email (`chau.tran@demo.local`) ở header và hồ sơ DW, vì `create_tenant` tạo chủ với
      `display_name` là email và lần đăng nhập đầu không đổi tên; (2) tag vai của chủ sở hữu ở header là "Vai khác" vì
      `ROLE_LABELS` (`apps/web/lib/nav/roles.ts`) không có `tenant_owner`; (3) "Chi phí model 0,00 USD" khi API trả
      `0.001642`: dưới 1 xu đọc như miễn phí, nên "< 0,01 USD"; (4) nút chat nổi đè lên nội dung ở cột trái (thấy ở
      hàng `work.handoff` của "Loại quyết định" ở 991 px và nhãn "Nội dung" của thẻ duyệt); (5) trong `Drawer` 560 px
      cột nhãn của gói bàn giao hẹp tới mức "Vấn đề" xuống hàng từng chữ. Tối và 991 px không thấy lỗi màu hay tràn
      ngang.
    - Quyết định (agent, theo ủy quyền 31/10/2026): compose project riêng `dwdemo` với volume mới mỗi lần chạy (Sàn
      chỉ cho một thư mỗi địa chỉ mỗi ngày, tenant tạo theo slug), không dùng chung `dwskel`. Nếu sai thì: bỏ
      `down -v` ở `up()` và cho seed đọc tenant đã có.
    - Quyết định (agent, theo ủy quyền 31/10/2026): demo dùng overlay thứ ba trên overlay dev, không sửa overlay dev
      (của máy chủ dùng chung, nghe 0.0.0.0); `INTAKE_SIGNING_SECRET`, `UNSUBSCRIBE_SIGNING_SECRET` chỉ nối trong
      overlay demo. Nếu sai thì: chuyển hai biến sang `docker-compose.dev.yml` với `${VAR:-}` để máy chủ dev cũng chạy
      được leadcare.
    - Quyết định (agent, theo ủy quyền 31/10/2026): `make demo-dw` luôn chạy model thật (`DW_MODEL_PROVIDER=openai`,
      `DW_API_MODEL_PROFILE=luna`, đổi được qua `DW_DEMO_MODEL_PROVIDER`/`DW_DEMO_MODEL_PROFILE`), bất kể `.env` để
      `mock`. Nếu sai thì: đọc thẳng `.env` và để người chạy tự đặt.
    - Quyết định (agent, theo ủy quyền 31/10/2026): demo chỉ chạy trong khung giờ của Sàn; không có đồng hồ giả cho
      Sàn ở worker và không thêm. Nếu sai thì: thêm một đồng hồ cấu hình được cho Sàn chỉ ở profile `local`, qua quyết
      định riêng.
    - Quyết định (agent, theo ủy quyền 31/10/2026): mỗi lượt dùng địa chỉ lead mới `lan.<8 hex>@example.com` để
      `demo-dw-again` không vấp trần tần suất của Sàn. Nếu sai thì: một địa chỉ cố định và chỉ `make demo-dw` (stack
      mới) mỗi ngày.
