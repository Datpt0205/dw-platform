# 01 — Gói Marketing chăm sóc lead, cửa nhận lead có chữ ký, công cụ email chỉ tới hộp thư dev

Status: resolved
Blocked by: .claude/plans/studio/wf-lite/issues/02-bien-dich-va-chay.md, .claude/plans/studio/compliance-pdpl/issues/08-loi-san-gui-tin.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, R2.12, R2.13, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, LCP1, LCP2, LCP3, LCP4, LCP5, LCP6, LCP7, LCP8, LCP9, LCP10, LCP11, LCP13, LCP14, LCP15, LCP16, LCP17, LCP18

## Mục tiêu

DW chăm sóc lead có quy trình, schema lead, prompt và công cụ của gói Marketing, nhận lead từ form
website qua một cửa có chữ ký, và gửi thư chỉ tới đúng lead đã đồng ý, chỉ tới hộp thư dev, chỉ sau khi
người duyệt, qua `ToolExecutor` (R1-R3).

## Việc cần làm

1. `configs/packs/marketing/workflows/lead_care@1.0.0.yaml` theo R1.1 và R1.2; biến `sender_address`
   (string), `sales_assignee_id` (uuid), `reply_wait_seconds` (integer, 30-604.800, mặc định 172.800),
   `min_confidence` (number, mặc định 0,7); `work_kinds` `marketing.lead` →
   `schemas/marketing.lead@1.0.0.json` theo R1.3.
2. Bốn prompt `configs/prompts/marketing/*@1.0.0.yaml` theo R1.4, đầu ra mỗi prompt có `confidence`
   0-1; chấm điểm `{score 0-100, tier A|B|C, reasons[≤5], confidence}`, soạn thư và thư nhắc `{subject ≤
150, body ≤ 4000, confidence}`, phân loại `{label: interested|not_interested|question|other, summary ≤
500, confidence}`.
3. Ba spec công cụ `configs/tools/email.send@1.0.0.yaml` (`external`, `idempotent: false`,
   `approval_policy: always`, `sends_message: true`, đầu vào `{to, subject, body}`, đầu ra có `sent_at`), `mailbox.fetch_reply@1.0.0.yaml`
   (`none`), `work.handoff@1.0.0.yaml` (`internal`); adapter `dw_connectors/adapters/smtp_email.py`
   (stdlib `smtplib` qua `asyncio.to_thread`, từ chối `send_sink_only` theo R3.6 trước khi mở kết nối,
   `send_outcome_unknown` theo R3.7) và `dw_connectors/adapters/mailpit_mailbox.py` (httpx tới
   `MAILBOX_API_URL`), nối ở composition root của worker; kiểm người nhận và đồng ý trong công cụ theo
   R3.2 với payload việc đọc từ `WorkQueue.get`, không từ đầu vào công cụ.
4. Migration mới: hàm `platform.intake_worker_scope(dw_id uuid) RETURNS TABLE(tenant_id uuid,
workspace_id uuid, state text)` `SECURITY DEFINER`, `SET search_path = pg_catalog, platform`,
   `EXECUTE` chỉ cho `dw_app`.
5. Route `apps/api/src/dw_api/routes/v1/intake.py`: `POST /v1/intake/leads` theo R2.1-R2.3, R2.9,
   R2.10 (so chữ ký bằng `hmac.compare_digest` trên `<timestamp>.<event_id>.<thân thô>`, đọc thân thô
   trước khi phân tích, thân tối đa 64 KiB); `GET /v1/digital-workers/{id}/intake-key` theo R2.4, R2.8,
   R2.11; `INTAKE_SIGNING_SECRET` trong settings theo R2.5, R2.7.
6. `mailpit` (ảnh `axllent/mailpit` ghim theo digest) trong `infra/compose/docker-compose.dev.yml`,
   chỉ cổng `127.0.0.1`; `SMTP_HOST`, `MAILBOX_API_URL` chỉ ở profile cục bộ.
7. `evals/datasets/leadcare_injection_v1.jsonl` và `make eval-leadcare` theo R1.5 (không chạy trong CI,
   cần khóa model trong `.env`).
8. Test: bộ kiểm trên tệp thật (LCP1), schema (LCP2), cửa nhận (LCP3-LCP8, LCP14), công cụ với SMTP và
   Mailpit giả (LCP9-LCP11, LCP13, LCP15), và một lượt integration với model giả đi từ cửa nhận tới bàn giao.
9. `reviewing-deployment-security` (route mới, dịch vụ compose mới, URL ra ngoài).

## Tiêu chí chấp nhận

- [x] R1.1 (LCP1): tệp thật qua bộ kiểm; bản sao đặt `email.send` ngoài lane `approved` trả `wf.hitl_gate_missing`.
- [x] R1.2: hai loại quyết định với đúng hiệu ứng, đảo được và trần; `email.send` trần A2.
- [x] R1.3 (LCP2): lead có trường lạ hay email sai → 422, không việc nào.
- [x] R1.4: bốn prompt nạp được, giá trị lead và thư trả lời xuất hiện trong `<input name="...">`.
- [ ] R1.5 (LCP16): `make eval-leadcare` trên ca chèn lệnh: người nhận của đề xuất vẫn là lead, nhãn đúng (ghi kết quả chạy vào Comments).
- [x] R2.1: chữ ký đúng → 202, việc `marketing.lead` thuộc tenant của DW; DW `paused` cũng 202, việc `open`.
- [x] R2.1 (LCP4): thân có `tenant_id` của tenant B → việc thuộc tenant của DW, B không có dòng nào.
- [x] R2.1 (LCP14): đổi `X-DW-Event-Id` giữ chữ ký cũ → 401.
- [x] R2.2 (LCP3): khóa của DW khác, timestamp lệch 301 giây, chữ ký rỗng, DW `retired` → bốn lần 401 cùng thân; lệch 300 giây thì nhận.
- [x] R2.3 (LCP5): `consent.granted = false` → 422 `consent_missing`, đếm việc không đổi.
- [x] R2.4: khóa ký bằng HMAC-SHA256 của id DW dưới bí mật máy chủ; không cột nào lưu khóa.
- [x] R2.8 (LCP6): Validator → 403; BO của DW khác cùng tenant → 403; người của tenant B → 404.
- [x] R2.11 (LCP6): Technical Owner đọc khóa → khóa ký hợp lệ và một dòng `dw.intake_key.read`.
- [x] R2.5 (LCP7): `is_deployed` với bí mật 16 byte → lỗi khởi động; 32 byte thì khởi động.
- [x] R2.7 (LCP7): profile cục bộ thiếu bí mật → cửa nhận 503 `intake_unconfigured`, không việc nào.
- [x] R2.6 (LCP8): hàm trả đúng ba cột; `dw_app` không ngữ cảnh đọc `platform.digital_workers` → 0 dòng.
- [x] R2.9: cùng event id cùng thân → 202 cùng id; khác thân → 409 `source_key_reused`.
- [x] R2.10: việc nhận được có một dòng `work_item.received` đứng tên actor của lane `intake`.
- [x] R3.1: thư tới Mailpit giả có người gửi là `sender_address`, người nhận là lead, header `X-DW-AI-Drafted` và dòng cuối về AI.
- [x] R3.2 (LCP9): `to` khác lead → `recipient_mismatch`, không thư.
- [x] R3.2 (LCP10): việc có payload không `consent.granted = true` → `consent_missing`, không thư.
- [x] R3.6 (LCP13): `is_deployed`, và `SMTP_HOST` `smtp.gmail.com` → `send_sink_only`, không kết nối SMTP nào được mở.
- [x] R3.7 (LCP15): SMTP giả hết giờ sau `DATA` → `send_outcome_unknown`, việc `handed_off`, đúng một lần thử.
- [x] R3.3: có thư trả lời sau lần gửi đầu → `{found: true, text}`; chưa có → `{found: false}`; thư trước lần gửi không tính.
- [x] R3.4 (LCP11): không `MAILBOX_API_URL` → việc `handed_off`, `problem` nêu `mailbox_unconfigured`.
- [x] R3.5: bàn giao cho `sales_assignee_id` với gói bốn trường; lane `rejected` bàn giao cho Validator.
- [x] R3.8: `reply_wait_seconds` 29 → `parameter_invalid`; 30 thì chạy.
- [x] R2.12 (LCP17): `is_deployed` → 503 `intake_disabled`, không việc nào.
- [x] R2.13 (LCP18): việc ghi xong có đúng một Bản ghi đồng ý `source = 'intake'`, `evidence_ref` là event id.
- [x] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `infra/compose/docker-compose.dev.yml:25-92`; `packages/python/dw_connectors/src/dw_connectors/adapters/zalo_bot.py:1`; spec: R1-R3, LCP1-LCP11, LCP13-LCP16.

## Comments

- 2026-10-29 (agent): viết lại theo gate `checking-plan-readiness` lượt 1.
- 2026-10-29 (agent): theo lượt xác nhận của gate: chờ compliance-pdpl/08 (Sàn gửi tin); `email.send` `approval_policy: always`, `sends_message: true`; cửa nhận ghi Bản ghi đồng ý và đóng khi `is_deployed`; `work.handoff` nhận `{to, code, facts}`; tiêu chí R1.5 kiểm điểm và nhãn (người nhận là tham chiếu khóa nên không đổi được); LCP3 thêm DW `draft`; LCP13 tách hai ca.
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-30 (agent): đang làm. Khoảng trống gặp khi bắt đầu: R1.1 cần `since` là `sent_at` của bước gửi và rẽ theo
  `found`, mà đầu ra của `tool.call` chỉ có `result`; quyết định tạm ở `Quyết định` của wf-lite (30/10): spec công cụ
  khai `output_fields`, bước ghi chúng cạnh `result`, bộ kiểm nhận `steps.<id>.<trường>`.
- 2026-10-30 (agent): đang làm. Xong bước 1-3 phần tệp và mã: gói `configs/packs/marketing` (quy trình, schema),
  bốn prompt, ba spec công cụ (`output_fields` cho `sent_at`, `found`, `text`), `configs/copy/leadcare_handoff.yaml`
  (`57ee004`); adapter `smtp_email.py`, `mailpit_mailbox.py` và `adapters/pack_tools.py` với ba handler (`bfa6b75`).
  Ba quyết định tạm thêm ở wf-lite (`Quyết định` 30/10): `min_confidence` nhận `{{ params.<tên> }}`; biến số có
  `minimum`/`maximum` (R3.8); tên tệp schema được chứa `@`. Còn, theo thứ tự: (a) settings `SMTP_HOST`, `SMTP_PORT`,
  `MAILBOX_API_URL` ở API và worker, `register_leadcare_tools` ở hai root (cần `RuntimeCopy` ở worker); (b) bước 4-5:
  migration `platform.intake_worker_scope`, route `POST /v1/intake/leads` và `GET /v1/digital-workers/{id}/intake-key`,
  `INTAKE_SIGNING_SECRET`, ghi `ConsentLedger` cùng giao dịch với việc (R2.13: cần đường ghi chung giao dịch); (c) bước
  6 Mailpit trong compose dev, đo API tìm kiếm của Mailpit thật; (d) bước 7 eval; (e) bước 8 test (LCP3-LCP18 và lượt
  integration từ cửa nhận tới bàn giao); (f) mutation, `reviewing-feature-security`, `reviewing-deployment-security`.
- 2026-10-30 (agent): đang làm. Xong (a) nối công cụ ở hai root (`8b51792`) và (b) cửa nhận: migration `cb43fb6e860b`,
  `application/intake.py`, route, `INTAKE_SIGNING_SECRET`, Bản ghi đồng ý cùng giao dịch với việc qua
  `WorkQueue.enqueue(intake=...)` (`6cf41ca`). Còn: test cửa nhận (đang viết), (c) Mailpit, (d) eval, (e) công cụ với
  SMTP/Mailpit giả và lượt integration từ cửa nhận tới bàn giao, (f) mutation và hai lượt rà bảo mật.
- 2026-10-30 (agent): resolved, trừ R1.5 (`57ee004` gói, `bfa6b75` công cụ, `8b51792` nối, `6cf41ca` cửa nhận,
  `0687ead` Mailpit, `8791a06` eval, `7b5156c`, `12a0141`, `9341032` test). Khác với ticket, ngoài các dòng trước:
  - R1.5 chưa chạy: máy này không có model thật (`.env` để `DW_MODEL_PROVIDER=mock`, không `OPENAI_BASE_URL`;
    `make check-model` cũng chỉ trả từ model giả). Bộ eval `leadcare_injection_v1.jsonl` (năm ca) và `make
    eval-leadcare` đã sẵn sàng và đã chạy tới bước gọi model; ô R1.5 để trống tới khi có khóa (`studio.md`, Chờ Đạt 21).
  - Cửa nhận: lead có trường lạ (kể cả `tenant_id`) bị schema từ chối `payload_invalid`, nên ca LCP4 kiểm "không dòng
    nào ở tenant B" bằng lời từ chối đó; `source_key_reused` đi theo `WorkQueue.enqueue` (422 như mọi lỗi
    `_refused` của hàng đợi, không 409 như R2.9 viết; mã lỗi đúng).
  - Công cụ `mailbox.fetch_reply` dùng loại quyết định `work.handoff` (không hiệu ứng); `work.handoff` không có
    `output_fields`. Mailpit ghim v1.31.6 (một HIGH có bản vá; v1.32.0 sạch nhưng mới 8 ngày, gộp vào Chờ Đạt 19).
  - `reviewing-feature-security`: tenant (tenant và workspace lấy từ dòng DW sau chữ ký; lead nêu tenant khác bị từ
    chối; hàm phạm vi chỉ ba cột); phân quyền (chữ ký là quyền duy nhất của cửa nhận, mọi lý do không tin là một 401;
    khóa chỉ cho BO/TO, 404 trước 403, có audit); tự chủ (thư chỉ đi qua cổng duyệt, Sàn gửi tin và cửa công cụ;
    người nhận đọc từ việc, khóa trong đề xuất); nội dung không tin cậy (mọi giá trị của lead và thư trả lời trong
    `<input>`; bộ eval chèn lệnh chờ chạy); audit (`work_item.received` của lane `intake` và Bản ghi đồng ý cùng giao
    dịch với việc; `dw.intake_key.read`); mặc định (cửa nhận đóng khi triển khai, 503 khi thiếu bí mật; công cụ gửi
    từ chối mọi host ngoài hộp thư dev trước khi kết nối). Test âm ở mỗi chỗ.
  - `reviewing-deployment-security` (bước 9): route công khai mới đóng 503 ở mọi profile triển khai và qua bộ giới
    hạn tốc độ theo địa chỉ; dịch vụ compose mới chỉ ở overlay dev, chỉ nghe loopback, ảnh ghim digest, đã quét
    trivy; URL ra ngoài: SMTP chỉ tới `mailpit`/`localhost`/`127.0.0.1`, `MAILBOX_API_URL` do người vận hành đặt và
    chỉ ở profile cục bộ.
  - Mutation `mutations/01.yaml`: 13/13 đỏ, đối chứng xanh.
  - Độ trễ `POST /api/v1/intake/leads` (route mới, không có số gốc), 200 lead ký đúng, ứng dụng ASGI thật và
    PostgreSQL thật: P50/P95/P99 47,3/56,9/63,0 ms (lần hai 44,1/54,8/64,5), trong ngân sách.
  - Cổng: ruff, format, mypy, `make test-unit` (1769), `test-contract`, `test-architecture`, kiểm manifest xanh;
    integration của `dw_platform`, `dw_agent_runtime`, `apps/api`, `apps/worker`: 794 qua, 3 bỏ qua.
