# 08 — Lõi sàn gửi tin: đồng ý, chặn gửi, tần suất, khung giờ, trần người nhận, nhật ký gửi, hủy nhận

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md, .claude/plans/studio/wf-lite/issues/02-bien-dich-va-chay.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R5.6, CP7, CP8, CP9, CP10, CP18, CP19, CP24

## Mục tiêu

Một tin marketing chỉ rời `ToolExecutor` khi qua Sàn gửi tin của ADR-0124 (Accepted), ở mọi profile, kể cả khi
người nhận là hộp thư dev: đây là phần lõi của ticket 04 tách ra để Digital Worker chăm sóc lead (leadcare/01)
gửi thư mà không đi trước cổng E1 (R3.1-R3.4, R3.6-R3.11, R5.6). Phần còn lại của ticket 04 (overlay công ty chỉ
siết, đối tượng Đồng ý của gói qua RecordService, bước trong sổ bước của tools-and-skills/01) ở lại ticket 04.

## Việc cần làm

1. Migration (id hex ngẫu nhiên), đúng bước 1 của ticket 04 cho ba bảng: `platform.consent_records` (chỉ thêm,
   toàn tenant, phân vùng tháng, một dòng `platform.time_partitioned_tables`), `platform.contact_suppressions` (PK
   `(tenant_id, channel, address_hash)`, toàn tenant, trigger `platform.guard_contact_suppression()` theo R5.6),
   `platform.marketing_send_log` (phân vùng tháng, RLS dạng workspace, `outcome` `dispatching` hay `blocked`,
   `blocked_reason`, `idempotency_key`, `channel`, `address_hash`, `root_run_id`, `consent_record_id`,
   `created_at`, index của bước 1 ticket 04); `dw_app` không quyền nào trên partition; tên và lý do của hai bảng
   toàn tenant trong danh sách của `test_rls_coverage.py`; hai mảnh retention như bước 1 ticket 04.
2. Xóa khi offboarding qua sổ bước xóa của foundations-hardening/07: một bước `platform.purge_tenant_marketing`
   (hàm SECURITY DEFINER nhận `tenant_id`, xóa dòng của đúng tenant đó ở ba bảng) đăng ký ở composition root của
   worker; ba dòng `STUDIO_EXCLUSIONS` với `function = platform.purge_tenant_marketing`.
3. `dw_platform/application/marketing_send.py`: `MarketingSendPolicy` thỏa `SendAdmissionPort` (do runtime khai)
   theo bước 2 của ticket 04 (thứ tự kiểm chặn gửi, đồng ý, tần suất, khung giờ theo múi giờ công ty, trần người
   nhận theo `root_run_id`; khóa tư vấn theo `(tenant_id, channel, address_hash)`; khóa chống lặp đã có dòng
   `dispatching` thì nhận ngay); `ConsentLedger.record(...)` ghi một Bản ghi đồng ý (`source`, `evidence_ref`,
   `notice_version`) cho bên nhận dữ liệu (leadcare/01).
4. `ToolExecutor`: một spec công cụ có `sends_message: true` (trường mới của `ToolSpec`, thay cho đánh dấu của
   manifest connector chưa có, ADR-0116 (Accepted)) đi qua `SendAdmissionPort` trước bước giành lượt và trước khi
   gọi công cụ, cho mọi đường tới executor (bước `tool.call` của wf-lite, lời gọi công cụ của agent); từ chối là
   `blocked:<lý do>`, audit `marketing.send_refused` và một dòng nhật ký `blocked` cùng giao dịch (R3.7); lời gọi
   `succeeded` ghi `marketing.sent` mang `consent_record_id` (R3.3).
5. `configs/policies/marketing_send@1.0.0.yaml` với số của ADR-0124 (Accepted) quyết 6 (1 tin mỗi địa chỉ mỗi kênh
   mỗi 24 giờ, 08:00-20:00 Asia/Ho_Chi_Minh, 200 người nhận mỗi lượt, UNVERIFIED); chưa có overlay công ty (ticket 04).
6. Route công khai `GET /api/v1/public/unsubscribe/{token}` theo bước 5 của ticket 04; công cụ gửi email chèn link
   hủy nhận ký HMAC một địa chỉ (ADR-0124 (Accepted) quyết 5).
7. Test âm CP7, CP8 (đường `tool.call` của wf-lite và đường công cụ của agent; quy trình dùng như công cụ chưa có,
   ghi ở Comments), CP9, CP10, CP18, CP19, CP24.
8. Đo P50/P95/P99 của lời gọi công cụ gửi tin có sàn so với không sàn (thêm câu lệnh trên đường ghi, `latency.md`).

## Tiêu chí chấp nhận

- [ ] R3.1 (CP7): lead không Bản ghi đồng ý → `blocked:no_consent`, 0 tin, `marketing.send_refused`; ở Danh sách chặn gửi → `blocked:suppressed`; 20:01 giờ công ty → `blocked:quiet_hours`.
- [ ] R3.2 (CP8): công cụ `sends_message` gọi qua bước `tool.call` và qua công cụ của agent mà không đồng ý → cả hai bị chặn ở executor; gỡ phép hỏi `SendAdmissionPort` khỏi executor → test đỏ.
- [ ] R3.3: tin được nhận ghi dòng `dispatching` mang `consent_record_id`; lời gọi `succeeded` ghi `marketing.sent` cùng `consent_record_id`.
- [ ] R3.4 (CP9): bấm link hủy → lần gửi sau `blocked:suppressed`.
- [ ] R3.6 (CP10): token sai chữ ký → 404, không dòng nào, cùng thân với token của địa chỉ không có.
- [ ] R3.7 (CP7): tin bị chặn có đúng một dòng nhật ký `blocked` với lý do, cùng giao dịch với audit.
- [ ] R3.8 (CP18): lượt gốc đã gửi tới 200 người nhận, tin tới người thứ 201 → `blocked:recipient_cap`.
- [ ] R3.9 (CP24): dòng `dispatching` đã commit trước khi công cụ giả nhận lời gọi (kết nối thứ hai thấy dòng).
- [ ] R3.10 (CP24): lần gửi thứ hai tới cùng địa chỉ trong 24 giờ với khóa khác, kể cả khi lần đầu `outcome_unknown` → `blocked:frequency_cap`.
- [ ] R3.11 (CP24): phát lại cùng khóa → không dòng thứ hai, không bị tính vào trần.
- [ ] R5.6 (CP19): `dw_app` DELETE một dòng chặn gửi của công ty `active` → 23514, dòng còn; lượt xóa offboarding xóa được.
- [ ] Xong: `make test-unit test-contract test-architecture && uv run pytest -m integration packages/python/dw_platform packages/python/dw_agent_runtime apps/api apps/worker` xanh.

## Nguồn

- `docs/adr/0124-marketing-messages-pass-a-platform-send-floor.md:1`; ticket 04 bước 1, 2, 5, 6; spec: R3, R5.6, CP7-CP10, CP18, CP19, CP24.

## Comments

- 2026-10-29 (agent, tạm theo ủy quyền): tách từ ticket 04 theo gate `checking-plan-readiness` của leadcare (CRITICAL: ADR-0124 (Accepted) đòi sàn trước tác động gửi đầu tiên ở mọi profile, kể cả người nhận thử), để lát Digital Worker gửi thư tới Mailpit mà không lách ADR. Ticket 04 chờ ticket này và giữ overlay, đối tượng Đồng ý và bước trong sổ bước của tools-and-skills/01. Nếu sai thì: gộp lại vào ticket 04 và leadcare/01 chờ ticket 04.
- 2026-10-29 (agent, tạm theo ủy quyền): đánh dấu gửi tin là trường `sends_message` của spec công cụ cho tới khi manifest connector của ADR-0116 (Accepted) có, rồi chuyển sang manifest. Nếu sai thì: chờ connections-and-vault cho manifest.
