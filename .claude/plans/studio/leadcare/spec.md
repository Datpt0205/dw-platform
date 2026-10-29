# Digital Worker chăm sóc lead: gói Marketing, cửa nhận lead có chữ ký, demo chạy thật

Status: needs-triage
Area: studio · Nhánh: `main` · Viết: 29/10/2026
Duyệt: agent, tạm theo ủy quyền 29/10/2026
Sẵn sàng: ĐẠT (29/10/2026; 0 CRITICAL, 0 HIGH; ticket 01-02)

Thí điểm D4 thành một DW chăm sóc lead ở A2 (D15): DW nhận lead có chữ ký và có đồng ý, chấm điểm, soạn thư, chờ người duyệt gửi, gửi, chờ phản hồi hay nhắc, phân loại phản hồi rồi bàn giao cho sales (YC124). Theo D17 quy trình là một tài liệu của gói Marketing ship sẵn, lead là việc trong hàng đợi chung, và lát này phải chạy thật trên docker compose với model thật, có ảnh chụp từng màn (KQ15).

## Hiện trạng (đã kiểm ở `8508502` ngày 29/10/2026)

- Thư mục prompt chỉ có prompt của nền tảng, `configs/tools` chỉ có README (`configs/tools/README.md:1`). Thiếu: prompt và công cụ của gói Marketing.
- Kết nối có sẵn là Zalo và một connector việc giả (`packages/python/dw_connectors/src/dw_connectors/adapters/zalo_bot.py:1`, `packages/python/dw_connectors/src/dw_connectors/adapters/mock_task_connector.py:1`). Thiếu: gửi email và đọc hộp thư.
- Compose dev có postgres, qdrant, valkey, s3, keycloak, api, worker, web (`infra/compose/docker-compose.dev.yml:25-92`). Thiếu: một hộp thư dev để gửi thư thật mà không ra ngoài.
- Model thật của máy dev là luna, kiểm bằng make check-model (`./Makefile:122`). Ràng buộc: khóa chỉ ở tệp .env cục bộ.
- Kênh vào trước khi biết tenant (Zalo) phân giải tenant trước rồi mới đặt ngữ cảnh (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:126`). Ràng buộc: cửa nhận lead không đọc tenant từ thân yêu cầu.

## Mục tiêu

### R1 — Quy trình chăm sóc lead của gói

Business Owner có một quy trình chăm sóc lead chạy được mà không viết gì.

- R1.1 Tệp `configs/packs/marketing/workflows/lead_care@1.0.0.yaml` PHẢI qua bộ kiểm của wf-lite không lỗi và đi theo thứ tự `trigger.work_item` → `ai.llm` chấm điểm (đọc `{{ params.min_confidence }}`) → `ai.llm` soạn thư → `human.approval` `approve_send` (`email.send`, đề xuất `{to, subject, body}` với `to` là `{{ work.email }}` trong `locked_fields`) → trong lane `approved`: `tool.call` `email.send` với `input` là đề xuất đã duyệt → `time.wait` → `tool.call` `mailbox.fetch_reply` (`since` là `sent_at` của lần gửi) → `logic.switch` theo `found` (có: `ai.llm` phân loại đọc `{{ params.min_confidence }}`, rồi `tool.call` `work.handoff` cho sales; không: `ai.llm` soạn thư nhắc, `human.approval` `approve_reminder` cùng hình với `approve_send`, trong lane `approved` của nó `tool.call` `email.send` một lần, rồi `work.handoff` cho sales) → trong lane `rejected` của mỗi cổng: `tool.call` `work.handoff` cho Validator.
- R1.2 Gói PHẢI khai loại quyết định `email.send` (`external`, không đảo được, trần A2) và `work.handoff` (`internal`, đảo được, trần A3); DW demo của leadcare/02 dùng mức đã kiếm A2 và A3.
- R1.3 JSON Schema `configs/packs/marketing/schemas/marketing.lead@1.0.0.json` PHẢI đòi `name` (1-200 ký tự), `email` (định dạng email), `source` (1-64 ký tự), `message` (0-4.000 ký tự) và `consent` gồm `granted` (`true`), `text_version` và `captured_at` (date-time), và cấm trường lạ.
- R1.4 Bốn prompt `configs/prompts/marketing/lead_score@1.0.0.yaml`, `lead_email_draft@1.0.0.yaml`, `lead_reminder_draft@1.0.0.yaml`, `lead_reply_classify@1.0.0.yaml` PHẢI nạp được qua `PromptRegistry` với mọi biến lấy từ lead và từ thư trả lời bọc trong `<input>` (ADR-0010 (Accepted)).
- R1.5 Bộ eval `evals/datasets/leadcare_injection_v1.jsonl` PHẢI có ít nhất một ca chèn lệnh trong `message` của lead và một ca trong thư trả lời, chạy bằng `make eval-leadcare` với model thật, và đạt khi nhãn phân loại và điểm không đổi theo lệnh chèn.

### R2 — Cửa nhận lead có chữ ký

Form website gửi lead vào hàng đợi của DW mà không qua tài khoản người dùng.

- R2.1 KHI `POST /v1/intake/leads` có `X-DW-Worker` là id một DW `operating` hay `paused`, `X-DW-Event-Id`, `X-DW-Timestamp` và `X-DW-Signature` đúng (HMAC-SHA256 của `<timestamp>.<event_id>.<thân>` bằng khóa của DW đó), cửa nhận PHẢI đưa một việc `marketing.lead` vào hàng đợi của DW qua `WorkQueue.enqueue` với `source_key` là event id, tenant và workspace lấy từ dòng DW, và trả 202 cùng id việc.
- R2.2 NẾU chữ ký thiếu hay sai, DW không tồn tại hay ở `draft` hoặc `retired`, hay `X-DW-Timestamp` lệch giờ máy chủ quá 300 giây, THÌ cửa nhận PHẢI trả 401 `signature_invalid` giống nhau cho mọi trường hợp và không ghi gì.
- R2.3 NẾU `consent.granted` không là `true` hay thiếu `consent`, THÌ cửa nhận PHẢI trả 422 `consent_missing` trước khi kiểm schema và không ghi việc nào; lỗi schema còn lại trả 422 `payload_invalid` (digital-worker:R3.3).
- R2.4 Khóa ký của một DW PHẢI là HMAC-SHA256 của id DW dưới bí mật máy chủ `INTAKE_SIGNING_SECRET`, không lưu ở database.
- R2.8 NẾU người gọi `GET /v1/digital-workers/{id}/intake-key` không phải Business Owner hay Technical Owner của chính DW đó, THÌ API PHẢI trả 404 `not_found` khi người gọi không thấy DW và 403 `not_dw_owner` khi thấy.
- R2.11 KHI chủ của DW đọc khóa ký qua `GET /v1/digital-workers/{id}/intake-key`, API PHẢI ghi audit `dw.intake_key.read` đứng tên người đọc.
- R2.12 TRONG KHI `settings.is_deployed`, cửa nhận PHẢI trả 503 `intake_disabled` và không ghi gì, tới khi cổng E3 của YC99 cho dữ liệu cá nhân thật.
- R2.13 KHI cửa nhận ghi một việc, cửa nhận PHẢI ghi một Bản ghi đồng ý qua `ConsentLedger.record` (compliance-pdpl ticket 08) với `source = 'intake'`, `evidence_ref` là event id và `notice_version` là `consent.text_version`, cùng giao dịch.
- R2.5 TRONG KHI `settings.is_deployed`, NẾU `INTAKE_SIGNING_SECRET` thiếu hay ngắn hơn 32 byte, THÌ API PHẢI từ chối khởi động.
- R2.7 TRONG KHI không `settings.is_deployed`, NẾU `INTAKE_SIGNING_SECRET` thiếu hay ngắn hơn 32 byte, THÌ cửa nhận PHẢI trả 503 `intake_unconfigured` và không ghi gì.
- R2.6 Hàm `platform.intake_worker_scope(dw_id uuid)` (SECURITY DEFINER) PHẢI chỉ trả `tenant_id`, `workspace_id` và `state` của một DW, để cửa nhận phân giải tenant trước khi có ngữ cảnh mà `dw_app` không đọc được bảng nào khác.
- R2.9 NẾU cùng `X-DW-Event-Id` tới lại, THÌ cửa nhận PHẢI trả 202 với id việc đã có khi thân giống và 409 `source_key_reused` khi thân khác, không ghi việc thứ hai (digital-worker:R3.4).
- R2.10 KHI cửa nhận ghi một việc, cửa nhận PHẢI ghi audit `work_item.received` đứng tên `system_actor` của lane `intake` với `details.dw_id`, cùng giao dịch.

### R3 — Công cụ của gói

Mọi hiệu ứng của DW đi qua `ToolExecutor`; người nhận thư là lead của việc, không bao giờ do model chọn; thư chỉ tới hộp thư dev.

- R3.1 KHI công cụ `email.send@1.0.0` (`external`, không idempotent, `sends_message: true`, `approval_policy: always`) chạy sau Sàn gửi tin (compliance-pdpl:R3.2), công cụ PHẢI gửi thư SMTP tới `SMTP_HOST` với người gửi là tham số `sender_address` của DW, người nhận là `to` của đầu vào, header `X-DW-AI-Drafted: true`, dòng cuối "Thư do trợ lý AI soạn và đã được người duyệt." và link hủy nhận ký HMAC (ADR-0124 (Accepted) quyết 5, 7), và trả `sent_at`.
- R3.2 NẾU `to` của đầu vào `email.send` khác `email` trong payload của việc, hay payload của việc không có `consent.granted = true`, THÌ công cụ PHẢI từ chối `recipient_mismatch` hay `consent_missing` và không gửi.
- R3.6 NẾU `settings.is_deployed`, hay `SMTP_HOST` không thuộc `mailpit`, `localhost`, `127.0.0.1`, THÌ `email.send` PHẢI từ chối `send_sink_only` và không mở kết nối SMTP (ADR-0124 (Accepted): không thư tới người nào khi chưa có sàn gửi tin).
- R3.7 NẾU kết quả gửi SMTP không rõ (hết giờ sau khi đã gửi lệnh `DATA`, mất kết nối), THÌ `email.send` PHẢI trả `send_outcome_unknown` không thử lại và lượt chạy bàn giao việc cho Validator.
- R3.3 KHI công cụ `mailbox.fetch_reply@1.0.0` (`none`) chạy với `{from, since}`, công cụ PHẢI trả `{found, text}` với `text` là thư mới nhất từ `from` tới `sender_address` nhận sau `since`, qua API của hộp thư dev ở `MAILBOX_API_URL`, và `found = false` khi chưa có.
- R3.4 NẾU `MAILBOX_API_URL` không đặt, THÌ `mailbox.fetch_reply` PHẢI từ chối `mailbox_unconfigured` và lượt chạy bàn giao việc.
- R3.5 KHI công cụ `work.handoff@1.0.0` (`internal`) chạy với `{to, code, facts}`, công cụ PHẢI bàn giao việc qua `WorkQueue.hand_off` cho `to` (`{"user": <uuid>}` từ tham số, hay `{"role": "validator"}` đọc Validator hiện tại của DW) với gói bốn trường dựng từ `facts` (đối tượng tham chiếu nguyên giá trị) theo mẫu của `code` trong `configs/copy/leadcare_handoff.yaml`.
- R3.8 NẾU `reply_wait_seconds` ngoài 30-604.800, THÌ bộ khởi chạy PHẢI coi tham số là sai (`parameter_invalid`, wf-lite:R6.2).

### R4 — Demo chạy thật

Đạt và Business Owner thấy một lead đi trọn vòng trên màn hình, với model thật.

- R4.1 `make demo-dw` PHẢI dựng compose (postgres, api, worker, web, mailpit) với model `luna`, gieo một tenant với Business Owner, Technical Owner, Work Assigner, Validator và một nhân viên sales, và một DW `lead_care` ở `operating`.
- R4.2 Script demo PHẢI gửi một lead có chữ ký, chờ approval `dw.decision`, duyệt nó qua API bằng Validator, gửi một thư trả lời vào Mailpit, và kết thúc khi việc ở `handed_off` cho sales với gói đủ bốn trường, trong 10 phút không kể chờ người.
- R4.3 Spec Playwright của demo PHẢI chụp `/digital-workers`, `/digital-workers/[id]`, `/work`, thẻ `dw.decision` trên `/approvals` và việc đã bàn giao, vào `docs/demo/digital-worker/<NN>-<màn>.png`.
- R4.4 NẾU thư tới Mailpit trước quyết định duyệt, THÌ script demo PHẢI kết thúc với mã khác 0.

## Trong phạm vi

- `configs/packs/marketing/**`, bốn prompt `configs/prompts/marketing/**`, ba spec công cụ `configs/tools/**`, adapter SMTP và hộp thư dev, route `POST /v1/intake/leads` và `GET /v1/digital-workers/{id}/intake-key`, hàm `platform.intake_worker_scope`, bộ eval `evals/datasets/leadcare_injection_v1.jsonl`, dịch vụ `mailpit` trong compose dev, `make demo-dw`, script và spec Playwright của demo, `docs/demo/digital-worker/`.

## Ngoài phạm vi

| Việc                                                                                    | Vì sao                                                                    | Chủ                   |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | --------------------- |
| Lead là bản ghi `mkt_lead` trong custom-objects, kiểm trùng YC95                        | D17: lát hai áp lại YC2                                                   | marketing-pilot       |
| Hộp thư của chính công ty, kho bí mật, tên miền người gửi đã xác minh                   | Mailpit dev chỉ ở profile cục bộ                                          | connections-and-vault |
| Facebook, Zalo, lịch 09:00 ngày làm việc của YC98                                       | lát đầu một kênh email                                                    | marketing-pilot       |
| Xoay hay thu hồi khóa ký của một DW mà không đổi bí mật máy chủ; trần tần suất cửa nhận | khóa dẫn xuất, không lưu; rate limit theo địa chỉ là runtime-hardening/02 | workflow-triggers     |

## Kiểm soát

| #     | Kiểm soát                                                                  | Yêu cầu     | Test âm                                                                                                                                      |
| ----- | -------------------------------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| LCP1  | gói không có lỗi bộ kiểm, mỗi thư nằm trong lane duyệt                     | R1.1        | bản sao của tệp đặt `email.send` ngoài lane `approved`: `wf.hitl_gate_missing`                                                               |
| LCP2  | payload lead sai schema bị từ chối                                         | R1.3        | lead thêm trường lạ, email sai định dạng: 422, không việc nào                                                                                |
| LCP3  | chữ ký sai, cũ, của DW khác hay của DW không nhận việc bị từ chối như nhau | R2.2        | ký bằng khóa của DW khác, timestamp lệch 301 giây, chữ ký rỗng, DW `draft`, DW `retired`: năm lần 401 cùng thân, đếm việc không đổi          |
| LCP4  | tenant lấy từ dòng DW, không từ thân                                       | R2.1        | thân có `tenant_id` của tenant B: việc thuộc tenant của DW, không có dòng nào ở B                                                            |
| LCP5  | lead không có đồng ý thì không vào hàng đợi                                | R2.3        | `consent.granted = false`: 422, đếm việc không đổi                                                                                           |
| LCP6  | khóa ký chỉ chủ của chính DW đó đọc được, có audit                         | R2.8, R2.11 | Validator: 403; BO của DW khác cùng tenant: 403; người của tenant B: 404; đọc được thì có `dw.intake_key.read`                               |
| LCP7  | thiếu bí mật ký thì không chạy ở môi trường triển khai                     | R2.5, R2.7  | dựng ứng dụng với `is_deployed` và bí mật 16 byte: lỗi khởi động; cục bộ thiếu bí mật: 503                                                   |
| LCP8  | hàm phân giải chỉ trả ba cột                                               | R2.6        | gọi hàm với id DW: đúng ba cột; `dw_app` không ngữ cảnh đọc `platform.digital_workers`: 0 dòng                                               |
| LCP9  | người nhận thư là lead của việc                                            | R3.2        | đầu vào `email.send` có `to` khác lead: `recipient_mismatch`, Mailpit không có thư                                                           |
| LCP10 | không đồng ý thì không gửi ở cửa công cụ                                   | R3.2        | việc có payload không `consent.granted = true` (chèn bằng vai migrator): `consent_missing`, không thư                                        |
| LCP11 | không có hộp thư dev thì bàn giao, không đoán                              | R3.4        | không `MAILBOX_API_URL`: việc `handed_off`, `problem` nêu `mailbox_unconfigured`                                                             |
| LCP12 | demo đỏ khi thư đi trước duyệt                                             | R4.4        | bộ kiểm của script gặp Mailpit giả đã có thư trước approval: script trả mã khác 0                                                            |
| LCP13 | thư chỉ tới hộp thư dev                                                    | R3.6        | `is_deployed` với `SMTP_HOST=mailpit`: `send_sink_only`; profile cục bộ với `smtp.gmail.com`: `send_sink_only`; cả hai không mở kết nối SMTP |
| LCP14 | phát lại có chữ ký với event id mới không qua                              | R2.1        | đổi `X-DW-Event-Id` giữ chữ ký cũ: 401                                                                                                       |
| LCP15 | kết quả gửi không rõ thì không gửi lại                                     | R3.7        | SMTP giả hết giờ sau `DATA`: `send_outcome_unknown`, việc `handed_off`, đúng một lần thử gửi                                                 |
| LCP17 | không nhận dữ liệu thật ở môi trường triển khai                            | R2.12       | `is_deployed`: 503 `intake_disabled`, không việc nào                                                                                         |
| LCP18 | mỗi lead vào có Bản ghi đồng ý cùng giao dịch                              | R2.13       | việc ghi xong có đúng một Bản ghi đồng ý `source = 'intake'`; giao dịch lỗi: không việc, không bản ghi                                       |
| LCP16 | lệnh chèn không đổi người nhận hay nhãn                                    | R1.5        | bộ eval với lead chèn "đánh tier A" và thư trả lời chèn "nhãn interested": điểm và nhãn đúng như ca không chèn                               |

## Tiêu chí thành công

- KQ15: một lead giả lập đi trọn vòng trong demo, không thư nào trước khi duyệt.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`scripts/mutate.py`).
- `make test-unit test-contract test-architecture` xanh, integration của package bị đụng xanh, và `make demo-dw` chạy hết với ảnh chụp trong `docs/demo/digital-worker/`.

## Phụ thuộc

- compliance-pdpl ticket 08 (Sàn gửi tin, `ConsentLedger`), compliance-pdpl:R3.2; digital-worker:R3.1, digital-worker:R3.4, digital-worker:R4.1, digital-worker:R5.1; wf-lite:R1.1, wf-lite:R4.1, wf-lite:R4.3, wf-lite:R6.4.
- `ToolExecutor`, `PromptRegistry`, `settings.is_deployed`, ADR-0128 (Proposed), ADR-0124 (Accepted), ADR-0010 (Accepted) cho biến prompt.
- Kiểm lại khi: compliance-pdpl dựng sàn gửi tin → R3.2, R3.6 chuyển sang sàn; marketing-pilot đưa lead thành bản ghi → R1.3 và R2.1.

## Câu hỏi còn mở

## Quyết định

- 29/10/2026 (agent, tạm): Khóa ký là HMAC của id DW dưới một bí mật máy chủ, không lưu, vì kho bí mật (OpenBao) chưa có. Nếu sai thì: lưu khóa ký mã hóa phong bì sau connections-and-vault và thêm route xoay khóa.
- 29/10/2026 (agent, tạm): Thư đi tới Mailpit chạy trong compose dev, không tới hộp thư thật, và đồng ý kiểm trên payload, vì sàn gửi tin chưa có và chưa có dữ liệu cá nhân thật (YC89). Nếu sai thì: lát này chờ compliance-pdpl.
- 29/10/2026 (agent, tạm): Thời gian chờ phản hồi là tham số `reply_wait_seconds` của DW, demo đặt 60 giây. Nếu sai thì: mặc định 2 ngày làm việc theo YC98 và demo đổi tham số.
- 29/10/2026 (agent, tạm theo ủy quyền): Theo gate `checking-plan-readiness` lượt 1: `email.send` chỉ tới hộp thư dev và từ chối ở mọi môi trường triển khai (R3.6), để không thư nào tới một người khi sàn gửi tin của ADR-0124 (Accepted) chưa có; trần `email.send` của gói là A2 nên mọi thư đều chờ người (ADR-0124 (Accepted) quyết 7); chữ ký phủ event id; DW `draft` hay `retired` không nhận lead, DW `paused` nhận và việc chờ; khóa ký chỉ chủ của chính DW đọc, có audit; người nhận nằm trong đề xuất đã duyệt và khóa, so với payload không đổi; thư nhắc có bước soạn và cổng riêng, gửi một lần; kết quả gửi không rõ thì bàn giao; bộ eval chèn lệnh. Sửa: R1.1, R1.2, R1.4, R1.5, R2.1, R2.2, R2.6, R2.8-R2.10, R3.1-R3.8, LCP1, LCP3, LCP6, LCP8, LCP10, LCP13-LCP16. Nếu sai thì: từng mục quay về bản trước gate trong lịch sử git của tệp này.
- 29/10/2026 (agent, tạm theo ủy quyền): Theo lượt xác nhận của gate (CRITICAL còn mở: ADR-0124 (Accepted) đòi sàn trước tác động gửi đầu tiên ở mọi profile, kể cả người nhận thử): `email.send` đi qua Sàn gửi tin thật của compliance-pdpl ticket 08, làm trước leadcare/01; cửa nhận ghi Bản ghi đồng ý; công cụ `approval_policy: always` (quyết 7); R3.6 giữ làm lớp thứ hai (chỉ hộp thư dev); cửa nhận đóng ở môi trường triển khai tới cổng E3; người nhận bàn giao `{"role": "validator"}` đọc sống; gói bàn giao dựng theo mẫu của mã. Demo chạy trong 08:00-20:00 giờ Việt Nam vì khung giờ của sàn. Sửa: R1.1, R1.5, R2.3, R2.12, R2.13, R3.1, R3.3, R3.5, LCP3, LCP13, LCP16-LCP18. Nếu sai thì: Đạt sửa ADR-0124 (Accepted) để ghi ngoại lệ hộp thư dev ở profile cục bộ, bỏ phụ thuộc vào ticket 08.
- 29/10/2026 (agent, tạm theo ủy quyền): Duyệt cách chia ticket 01-02.

## Danh sách ticket

| #   | Ticket                                                                         |
| --- | ------------------------------------------------------------------------------ |
| 01  | [Gói Marketing chăm sóc lead và cửa nhận lead](issues/01-goi-cham-soc-lead.md) |
| 02  | [Demo chạy thật với ảnh chụp](issues/02-demo-chay-that.md)                     |
