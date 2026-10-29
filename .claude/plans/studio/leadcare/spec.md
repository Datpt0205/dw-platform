# Digital Worker chăm sóc lead: gói Marketing, cửa nhận lead có chữ ký, demo chạy thật

Status: needs-triage
Area: studio · Nhánh: `main` · Viết: 29/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

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

- R1.1 Tệp `configs/packs/marketing/workflows/lead_care@1.0.0.yaml` PHẢI qua bộ kiểm của wf-lite không lỗi và đi theo thứ tự `trigger.work_item` → `ai.llm` chấm điểm (`lead.score`) → `ai.llm` soạn thư (`email.draft`) → `human.approval` (`email.send`) → `tool.call` `email.send` → `time.wait` → `tool.call` `mailbox.fetch_reply` → `ai.llm` phân loại (`reply.classify`) → `logic.switch` theo nhãn (nhãn `no_reply`: `human.approval` rồi `tool.call` thư nhắc) → `tool.call` `work.handoff` cho sales.
- R1.2 Gói PHẢI khai loại quyết định `lead.score` (`none`, trần A3, khởi đầu A3), `email.draft` (`none`, trần A3, khởi đầu A3), `email.send` (`external`, không đảo được, trần A3, khởi đầu A2), `reply.classify` (`none`, trần A3, khởi đầu A3) và `work.handoff` (`internal`, đảo được, trần A3, khởi đầu A3).
- R1.3 JSON Schema `configs/packs/marketing/schemas/marketing.lead@1.0.0.json` PHẢI đòi `name` (1-200 ký tự), `email` (định dạng email), `source` (1-64 ký tự), `message` (0-4.000 ký tự) và `consent` gồm `granted` (`true`), `text_version` và `captured_at` (date-time), và cấm trường lạ.
- R1.4 Ba prompt `configs/prompts/marketing/lead_score@1.0.0.yaml`, `lead_email_draft@1.0.0.yaml`, `lead_reply_classify@1.0.0.yaml` PHẢI nạp được qua `PromptRegistry` với mọi biến lấy từ lead bọc trong `<input>`.

### R2 — Cửa nhận lead có chữ ký

Form website gửi lead vào hàng đợi của DW mà không qua tài khoản người dùng.

- R2.1 KHI `POST /v1/intake/leads` có `X-DW-Worker` là id một DW, `X-DW-Event-Id`, `X-DW-Timestamp` và `X-DW-Signature` đúng (HMAC-SHA256 của `<timestamp>.<thân>` bằng khóa của DW đó), cửa nhận PHẢI đưa một việc `marketing.lead` vào hàng đợi của DW qua `WorkQueue.enqueue` với `source_key` là event id, tenant và workspace lấy từ dòng DW, và trả 202 cùng id việc.
- R2.2 NẾU chữ ký thiếu hay sai, DW không tồn tại, hay `X-DW-Timestamp` lệch giờ máy chủ quá 300 giây, THÌ cửa nhận PHẢI trả 401 `signature_invalid` giống nhau cho mọi trường hợp và không ghi gì.
- R2.3 NẾU `consent.granted` không là `true` hay thiếu `consent`, THÌ cửa nhận PHẢI trả 422 `consent_missing` và không ghi việc nào.
- R2.4 Khóa ký của một DW PHẢI là HMAC-SHA256 của id DW dưới bí mật máy chủ `INTAKE_SIGNING_SECRET`, không lưu ở database, và chỉ Business Owner hay Technical Owner đọc được qua `GET /v1/digital-workers/{id}/intake-key`.
- R2.5 NẾU `INTAKE_SIGNING_SECRET` thiếu hay ngắn hơn 32 byte, THÌ API PHẢI từ chối khởi động khi `settings.is_deployed`, và cửa nhận PHẢI trả 503 ở profile khác.
- R2.6 Hàm `platform.intake_worker_scope(dw_id uuid)` (SECURITY DEFINER) PHẢI chỉ trả `tenant_id` và `workspace_id` của một DW, để cửa nhận phân giải tenant trước khi có ngữ cảnh mà `dw_app` không đọc được bảng nào khác.

### R3 — Công cụ của gói

Mọi hiệu ứng của DW đi qua `ToolExecutor`; người nhận thư không bao giờ do model chọn.

- R3.1 KHI công cụ `email.send@1.0.0` (`external`, không idempotent) chạy, công cụ PHẢI gửi thư SMTP tới `SMTP_HOST` với người gửi là tham số `sender_address` của DW và người nhận là `email` trong payload của việc.
- R3.2 NẾU đầu vào của `email.send` nêu người nhận khác `email` của việc, hay payload của việc không có `consent.granted = true`, THÌ công cụ PHẢI từ chối `recipient_mismatch` hay `consent_missing` và không gửi.
- R3.3 KHI công cụ `mailbox.fetch_reply@1.0.0` (`none`) chạy, công cụ PHẢI trả thư mới nhất từ `email` của lead tới `sender_address` qua API của hộp thư dev ở `MAILBOX_API_URL`, hay `null` khi chưa có.
- R3.4 NẾU `MAILBOX_API_URL` không đặt, THÌ `mailbox.fetch_reply` PHẢI từ chối `mailbox_unconfigured` và lượt chạy bàn giao việc.
- R3.5 KHI công cụ `work.handoff@1.0.0` (`internal`) chạy, công cụ PHẢI bàn giao việc qua `WorkQueue.hand_off` cho tham số `sales_assignee_id` của DW với gói dựng từ điểm, thư đã gửi và phân loại phản hồi.

### R4 — Demo chạy thật

Đạt và Business Owner thấy một lead đi trọn vòng trên màn hình, với model thật.

- R4.1 `make demo-dw` PHẢI dựng compose (postgres, api, worker, web, mailpit) với model `luna`, gieo một tenant với Business Owner, Technical Owner, Work Assigner, Validator và một nhân viên sales, và một DW `lead_care` ở `operating`.
- R4.2 Script demo PHẢI gửi một lead có chữ ký, chờ approval `dw.decision`, duyệt nó qua API bằng Validator, gửi một thư trả lời vào Mailpit, và kết thúc khi việc ở `handed_off` cho sales với gói đủ bốn trường, trong 10 phút không kể chờ người.
- R4.3 Spec Playwright của demo PHẢI chụp `/digital-workers`, `/digital-workers/[id]`, `/work`, thẻ `dw.decision` trên `/approvals` và việc đã bàn giao, vào `docs/demo/digital-worker/<NN>-<màn>.png`.
- R4.4 NẾU thư tới Mailpit trước quyết định duyệt, THÌ script demo PHẢI kết thúc với mã khác 0.

## Trong phạm vi

- `configs/packs/marketing/**`, ba prompt `configs/prompts/marketing/**`, ba spec công cụ `configs/tools/**`, adapter SMTP và hộp thư dev, route `POST /v1/intake/leads` và `GET /v1/digital-workers/{id}/intake-key`, hàm `platform.intake_worker_scope`, dịch vụ `mailpit` trong compose dev, `make demo-dw`, script và spec Playwright của demo, `docs/demo/digital-worker/`.

## Ngoài phạm vi

| Việc                                                             | Vì sao                                                  | Chủ                   |
| ---------------------------------------------------------------- | ------------------------------------------------------- | --------------------- |
| Lead là bản ghi `mkt_lead` trong custom-objects, kiểm trùng YC95 | D17: lát hai áp lại YC2                                 | marketing-pilot       |
| Sàn gửi tin và sổ đồng ý của nền tảng (ADR-0124 (Accepted))      | lát đầu kiểm đồng ý trên payload và chỉ gửi tới Mailpit | compliance-pdpl       |
| Hộp thư của chính công ty, kho bí mật                            | Mailpit dev chỉ ở profile cục bộ                        | connections-and-vault |
| Facebook, Zalo, lịch 09:00 ngày làm việc của YC98                | lát đầu một kênh email                                  | marketing-pilot       |
| Xoay khóa ký mà không đổi bí mật máy chủ                         | khóa dẫn xuất, không lưu                                | workflow-triggers     |

## Kiểm soát

| #     | Kiểm soát                                              | Yêu cầu | Test âm                                                                                                  |
| ----- | ------------------------------------------------------ | ------- | -------------------------------------------------------------------------------------------------------- |
| LCP1  | gói không có lỗi bộ kiểm và có cổng trước mỗi thư      | R1.1    | bỏ bước `human.approval` khỏi bản sao của tệp: bộ kiểm trả `wf.hitl_gate_missing`                        |
| LCP2  | payload lead sai schema bị từ chối                     | R1.3    | lead thêm trường lạ, email sai định dạng: 422, không việc nào                                            |
| LCP3  | chữ ký sai, cũ hay của DW khác bị từ chối như nhau     | R2.2    | ký bằng khóa của DW khác, timestamp lệch 301 giây, chữ ký rỗng: ba lần 401 cùng thân, đếm việc không đổi |
| LCP4  | tenant lấy từ dòng DW, không từ thân                   | R2.1    | thân có `tenant_id` của tenant B: việc thuộc tenant của DW, không có dòng nào ở B                        |
| LCP5  | lead không có đồng ý thì không vào hàng đợi            | R2.3    | `consent.granted = false`: 422, đếm việc không đổi                                                       |
| LCP6  | khóa ký chỉ chủ DW đọc được                            | R2.4    | Validator gọi `/intake-key`: 403                                                                         |
| LCP7  | thiếu bí mật ký thì không chạy ở môi trường triển khai | R2.5    | dựng ứng dụng với `is_deployed` và bí mật 16 byte: lỗi khởi động                                         |
| LCP8  | hàm phân giải chỉ trả hai cột                          | R2.6    | gọi hàm với id DW: đúng hai cột; `dw_app` không ngữ cảnh đọc `platform.digital_workers`: 0 dòng          |
| LCP9  | người nhận thư không do model chọn                     | R3.2    | đầu vào `email.send` có người nhận khác lead: từ chối, Mailpit không có thư                              |
| LCP10 | không đồng ý thì không gửi ở cửa công cụ               | R3.2    | payload việc sửa `consent.granted = false` sau khi vào hàng đợi: từ chối `consent_missing`               |
| LCP11 | không có hộp thư dev thì bàn giao, không đoán          | R3.4    | không `MAILBOX_API_URL`: việc `handed_off`, `problem` nêu `mailbox_unconfigured`                         |
| LCP12 | demo đỏ khi thư đi trước duyệt                         | R4.4    | bộ kiểm của script gặp Mailpit giả đã có thư trước approval: script trả mã khác 0                        |

## Tiêu chí thành công

- KQ15: một lead giả lập đi trọn vòng trong demo, không thư nào trước khi duyệt.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`scripts/mutate.py`).
- `make test-unit test-contract test-architecture` xanh, integration của package bị đụng xanh, và `make demo-dw` chạy hết với ảnh chụp trong `docs/demo/digital-worker/`.

## Phụ thuộc

- digital-worker:R3.1, digital-worker:R4.1, digital-worker:R5.1; wf-lite:R1.1, wf-lite:R4.1, wf-lite:R6.4.
- `ToolExecutor`, `PromptRegistry`, `settings.is_deployed`, ADR-0128 (Proposed), ADR-0010 (Accepted) cho biến prompt.
- Kiểm lại khi: compliance-pdpl dựng sàn gửi tin → R3.2 chuyển sang sàn; marketing-pilot đưa lead thành bản ghi → R1.3 và R2.1.

## Câu hỏi còn mở

## Quyết định

- 29/10/2026 (agent, tạm): Khóa ký là HMAC của id DW dưới một bí mật máy chủ, không lưu, vì kho bí mật (OpenBao) chưa có. Nếu sai thì: lưu khóa ký mã hóa phong bì sau connections-and-vault và thêm route xoay khóa.
- 29/10/2026 (agent, tạm): Thư đi tới Mailpit chạy trong compose dev, không tới hộp thư thật, và đồng ý kiểm trên payload, vì sàn gửi tin chưa có và chưa có dữ liệu cá nhân thật (YC89). Nếu sai thì: lát này chờ compliance-pdpl.
- 29/10/2026 (agent, tạm): Thời gian chờ phản hồi là tham số `reply_wait_seconds` của DW, demo đặt 60 giây. Nếu sai thì: mặc định 2 ngày làm việc theo YC98 và demo đổi tham số.

## Danh sách ticket

| #   | Ticket                                                                         |
| --- | ------------------------------------------------------------------------------ |
| 01  | [Gói Marketing chăm sóc lead và cửa nhận lead](issues/01-goi-cham-soc-lead.md) |
| 02  | [Demo chạy thật với ảnh chụp](issues/02-demo-chay-that.md)                     |
