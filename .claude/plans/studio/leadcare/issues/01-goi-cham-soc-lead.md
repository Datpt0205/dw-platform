# 01 — Gói Marketing chăm sóc lead, cửa nhận lead có chữ ký, công cụ email qua Mailpit

Status: needs-triage
Blocked by: .claude/plans/studio/wf-lite/issues/02-bien-dich-va-chay.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R3.1, R3.2, R3.3, R3.4, R3.5, LCP1, LCP2, LCP3, LCP4, LCP5, LCP6, LCP7, LCP8, LCP9, LCP10, LCP11

## Mục tiêu

DW chăm sóc lead có quy trình, schema lead, prompt và công cụ của gói Marketing, nhận lead từ form
website qua một cửa có chữ ký, và gửi thư chỉ tới đúng lead đã đồng ý, qua `ToolExecutor` (R1-R3).

## Việc cần làm

1. `configs/packs/marketing/workflows/lead_care@1.0.0.yaml` theo R1.1 và R1.2; biến `sender_address`
   (string), `sales_assignee_id` (uuid), `reply_wait_seconds` (integer, mặc định 172800),
   `min_confidence` (number, mặc định 0,7); `work_kinds` `marketing.lead` →
   `schemas/marketing.lead@1.0.0.json` theo R1.3.
2. Ba prompt `configs/prompts/marketing/*@1.0.0.yaml` theo R1.4, đầu ra mỗi prompt có `confidence`
   0-1; đầu ra chấm điểm `{score 0-100, tier A|B|C, reasons[≤5], confidence}`, soạn thư `{subject ≤
150, body ≤ 4000, confidence}`, phân loại `{label: interested|not_interested|question|no_reply,
summary ≤ 500, confidence}`.
3. Ba spec công cụ `configs/tools/email.send@1.0.0.yaml` (`external`, `idempotent: false`,
   `approval_policy: conditional`), `mailbox.fetch_reply@1.0.0.yaml` (`none`),
   `work.handoff@1.0.0.yaml` (`internal`); adapter `dw_connectors/adapters/smtp_email.py` (stdlib
   `smtplib` qua `asyncio.to_thread`) và `dw_connectors/adapters/mailpit_mailbox.py` (httpx tới
   `MAILBOX_API_URL`), nối ở composition root của worker; kiểm người nhận và đồng ý trong công cụ theo
   R3.2 với payload việc đọc từ `WorkQueue.get`, không từ đầu vào công cụ.
4. Migration mới: hàm `platform.intake_worker_scope(dw_id uuid) RETURNS TABLE(tenant_id uuid,
workspace_id uuid)` `SECURITY DEFINER`, `SET search_path = pg_catalog, platform`, `EXECUTE` chỉ cho
   `dw_app`.
5. Route `apps/api/src/dw_api/routes/v1/intake.py`: `POST /v1/intake/leads` theo R2.1-R2.3 (so chữ ký
   bằng `hmac.compare_digest`, đọc thân thô trước khi phân tích, thân tối đa 64 KiB); `GET
/v1/digital-workers/{id}/intake-key` theo R2.4; `INTAKE_SIGNING_SECRET` trong settings theo R2.5.
6. `mailpit` (ảnh `axllent/mailpit` ghim theo digest) trong `infra/compose/docker-compose.dev.yml`,
   chỉ cổng `127.0.0.1`; `SMTP_HOST`, `MAILBOX_API_URL` chỉ ở profile cục bộ.
7. Test: bộ kiểm trên tệp thật (LCP1), schema (LCP2), cửa nhận (LCP3-LCP8), công cụ với Mailpit giả
   (LCP9-LCP11), và một lượt integration với model giả đi từ cửa nhận tới bàn giao.
8. `reviewing-deployment-security` (route mới, dịch vụ compose mới, URL ra ngoài).

## Tiêu chí chấp nhận

- [ ] R1.1 (LCP1): tệp thật qua bộ kiểm; bản sao bỏ `human.approval` trả `wf.hitl_gate_missing`.
- [ ] R1.2: năm loại quyết định với đúng hiệu ứng, trần và mức khởi đầu.
- [ ] R1.3 (LCP2): lead có trường lạ hay email sai → 422, không việc nào.
- [ ] R1.4: ba prompt nạp được, giá trị lead xuất hiện trong `<input name="...">`.
- [ ] R2.1: chữ ký đúng → 202, việc `marketing.lead` thuộc tenant của DW.
- [ ] R2.1 (LCP4): thân có `tenant_id` của tenant B → việc thuộc tenant của DW, B không có dòng nào.
- [ ] R2.2 (LCP3): khóa của DW khác, timestamp lệch 301 giây, chữ ký rỗng → ba lần 401 cùng thân; lệch 300 giây thì nhận.
- [ ] R2.3 (LCP5): `consent.granted = false` → 422 `consent_missing`, đếm việc không đổi.
- [ ] R2.4 (LCP6): Validator đọc khóa → 403; Technical Owner đọc được khóa ký hợp lệ.
- [ ] R2.5 (LCP7): `is_deployed` với bí mật 16 byte → lỗi khởi động; 32 byte thì khởi động.
- [ ] R2.7 (LCP7): profile cục bộ thiếu bí mật → cửa nhận 503 `intake_unconfigured`, không việc nào.
- [ ] R2.6 (LCP8): hàm trả đúng hai cột; `dw_app` không ngữ cảnh đọc `platform.digital_workers` → 0 dòng.
- [ ] R3.1: thư tới Mailpit giả có người gửi là `sender_address`, người nhận là email của lead.
- [ ] R3.2 (LCP9): người nhận khác lead → `recipient_mismatch`, không thư.
- [ ] R3.2 (LCP10): payload sửa `consent.granted = false` → `consent_missing`, không thư.
- [ ] R3.3: có thư trả lời → trả nội dung; chưa có → `null`.
- [ ] R3.4 (LCP11): không `MAILBOX_API_URL` → việc `handed_off`, `problem` nêu `mailbox_unconfigured`.
- [ ] R3.5: bàn giao cho `sales_assignee_id` với gói có điểm, thư đã gửi và phân loại.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `infra/compose/docker-compose.dev.yml:25-92`; `packages/python/dw_connectors/src/dw_connectors/adapters/zalo_bot.py:1`; spec: R1-R3, LCP1-LCP11.

## Comments
