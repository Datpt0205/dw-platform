# 08 — Lõi sàn gửi tin: đồng ý, chặn gửi, tần suất, khung giờ, trần người nhận, nhật ký gửi, hủy nhận

Status: ready-for-agent
Blocked by: .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md, .claude/plans/studio/wf-lite/issues/02-bien-dich-va-chay.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R5.6, CP7, CP8, CP9, CP10, CP18, CP19, CP24, CP27, CP28, CP29

## Mục tiêu

Một tin marketing chỉ rời `ToolExecutor` khi qua Sàn gửi tin của ADR-0124 (Accepted), ở mọi profile, kể cả khi
người nhận là hộp thư dev: đây là phần lõi của ticket 04 tách ra để Digital Worker chăm sóc lead (leadcare/01)
gửi thư mà không đi trước cổng E1 (R3.1-R3.4, R3.6-R3.11, R5.6). Phần còn lại của ticket 04 (overlay công ty chỉ
siết, đối tượng Đồng ý của gói qua RecordService, bước trong sổ bước của tools-and-skills/01) ở lại ticket 04.

## Việc cần làm

1. Migration (id hex ngẫu nhiên), đúng bước 1 của ticket 04 cho ba bảng: `platform.consent_records` (chỉ thêm,
   toàn tenant, phân vùng tháng, một dòng `platform.time_partitioned_tables`, `state` CHECK trong `granted`,
   `withdrawn`), `platform.contact_suppressions` (PK `(tenant_id, channel, address_hash)`, toàn tenant, trigger
   `platform.guard_contact_suppression()` theo R5.6, `dw_app` có DELETE chỉ dùng được khi tenant `offboarding`),
   `platform.marketing_send_log` (phân vùng tháng, RLS dạng workspace, cột và index của bước 1 ticket 04); `dw_app`
   không quyền nào trên partition; tên và lý do của hai bảng toàn tenant trong danh sách của `test_rls_coverage.py`;
   hai mảnh retention như bước 1 ticket 04; mọi policy mới theo dạng đọc setting trong sub-SELECT
   (foundations-hardening R5.3).
2. Đếm trên toàn tenant: hàm SECURITY DEFINER `platform.marketing_sends_since(channel, address_hash, since)` và
   `platform.marketing_recipients_of_run(root_run_id)` đếm dòng `dispatching` của tenant trong `app.tenant_id`, mọi
   workspace, chỉ trả số đếm, RAISE khi `app.tenant_id` trống, `EXECUTE` chỉ cho `dw_app`; trần tần suất là của tenant (bên kiểm soát, ADR-0124 (Accepted)
   (Accepted) quyết 4), không của workspace.
3. Xóa khi offboarding qua sổ bước xóa của foundations-hardening/07: một bước `platform.purge_tenant_marketing`
   (hàm SECURITY DEFINER nhận `tenant_id`, RAISE khi `platform.tenants.status` của tenant đó khác `offboarding` hay khác `app.tenant_id` của giao dịch, xóa
   dòng của đúng tenant đó ở `consent_records` và `marketing_send_log`, `EXECUTE` chỉ cho `dw_app`) đăng ký ở
   composition root của worker; `contact_suppressions` theo bước mặc định của sổ (DELETE của `dw_app`, trigger cho
   phép khi `offboarding`); dòng `STUDIO_EXCLUSIONS` cho hai bảng phân vùng với `function =
platform.purge_tenant_marketing`. Thêm một dòng Comments vào usage-and-limits/02 rằng `platform.purge_tenant_append_only`
   phải bỏ qua bảng đã có bước khai (R11.8 của foundations-hardening từ chối hai bước cùng một bảng).
4. `dw_platform/application/marketing_send.py`: `MarketingSendPolicy` thỏa `SendAdmissionPort(admit(context,
request) -> Admission)` (runtime khai); thứ tự kiểm chặn gửi, đồng ý (dòng mới nhất theo `(subject, purpose,
channel)`, `granted` thì `no_consent` không áp, `withdrawn` thì `consent_withdrawn`, không có thì `no_consent`),
   tần suất, khung giờ 08:00-20:00 `Asia/Ho_Chi_Minh` cố định của ADR-0124 (Accepted) quyết 6, không đọc múi giờ của
   công ty, trần người nhận; khóa tư vấn của giao dịch theo `(tenant_id, channel, address_hash)` và theo
   `root_run_id`; lời gọi có khóa chống lặp đã có dòng `dispatching` không ghi dòng mới và không bị đếm vào hai trần
   nhưng vẫn kiểm lại chặn gửi và đồng ý (R3.11, ADR-0124 (Accepted) quyết 5); lần chặn đầu ghi dòng `blocked` và
   `marketing.send_refused` trong một giao dịch của chính policy, lần phát lại bị chặn chỉ ghi `marketing.send_refused` với
   `details.replay = true` (R3.7); lấy khóa tư vấn theo địa chỉ trước rồi theo `root_run_id`; nhận thì trả `Admission`
   mang `unsubscribe_url` để executor đưa vào đầu vào của công cụ (`_unsubscribe_url`), công cụ gửi tin nào cũng chèn. `ConsentLedger.record(...)` ghi một Bản ghi
   đồng ý cho bên nhận dữ liệu (leadcare/01). `root_run_id` của lát này là `run_id` (wf-lite chưa có lượt con).
5. Địa chỉ: một hàm `normalize_address(channel, value)` (email: cắt khoảng trắng, chữ thường) và
   `address_hash = sha256(tenant_id || channel || địa chỉ chuẩn hóa)`, dùng chung cho sàn, chặn gửi và token hủy.
6. `ToolExecutor`: `ToolSpec` có `sends_message` bắt buộc khai (không mặc định) với mọi công cụ có `side_effect_level`
   khác `none`, và `sends_message: true` đòi khối `message: {channel, recipient_fields}` liệt kê mọi trường địa chỉ của
   đầu vào (to, cc, bcc); thiếu hay lệch nhau thì nạp spec lỗi (đóng khi thiếu); khi tools-and-skills đặt `effect_class:
message`, hai dấu phải khớp hoặc nạp lỗi; `configs/tools` hôm nay không có spec `external` nào phải sửa; công cụ gửi tin đi qua `SendAdmissionPort` sau phép kiểm approval và sau phép
   phát lại `find_succeeded`, trước bước giành lượt, cho mọi đường tới executor; đầu vào có hơn một địa chỉ trên mọi trường của
   `recipient_fields` gộp lại → `blocked:multiple_recipients`; đường quy trình dùng như công cụ chưa có (R3.2 phủ khi có).
7. `configs/policies/marketing_send@1.0.0.yaml` với số của ADR-0124 (Accepted) quyết 6 (UNVERIFIED); chưa có overlay
   công ty (ticket 04).
8. Hủy nhận: `unsubscribe_link(tenant_id, channel, address)` ký HMAC-SHA256 bằng `UNSUBSCRIBE_SIGNING_SECRET`
   (≥ 32 byte; thiếu thì API không khởi động khi `is_deployed`), token mang `tenant_id`, `channel`, `address_hash`,
   `issued_at` (token quá 400 ngày → 404), không mang địa chỉ; trang `apps/web/app/unsubscribe/[token]` (antd, không
   đăng nhập) hỏi xác nhận, `GET /api/v1/public/unsubscribe/{token}` chỉ kiểm token, `POST` cùng đường ghi dòng chặn gửi
   (idempotent), để trình quét link của hộp thư không tự hủy; tenant lấy từ token đã kiểm chữ ký; token sai → 404 cùng
   thân ở cả hai; hai route qua bộ giới hạn tốc độ theo địa chỉ IP sẵn có (ADR-0124 (Accepted) quyết 5); thiếu bí mật ở
   profile không triển khai → 503.
9. Test âm CP7-CP10, CP18, CP19, CP24, CP27-CP29.
10. Đo P50/P95/P99 của lời gọi công cụ gửi tin có sàn so với không sàn (thêm câu lệnh trên đường ghi, `latency.md`).

## Tiêu chí chấp nhận

- [ ] R3.1 (CP7): không Bản ghi đồng ý → `blocked:no_consent`, 0 tin, `marketing.send_refused`; đồng ý `withdrawn` → `blocked:consent_withdrawn`; ở Danh sách chặn gửi → `blocked:suppressed`; 20:01 và 07:59 giờ Việt Nam → `blocked:quiet_hours`, 08:00 thì gửi; đổi múi giờ của công ty không đổi kết quả.
- [ ] R3.2 (CP8): công cụ `sends_message` gọi qua bước `tool.call` và qua công cụ của agent mà không đồng ý → cả hai bị chặn ở executor; gỡ phép hỏi `SendAdmissionPort` → test đỏ.
- [ ] R3.3: tin được nhận ghi dòng `dispatching` mang `consent_record_id`; lời gọi `succeeded` ghi `marketing.sent` cùng `consent_record_id`.
- [ ] R3.4 (CP9): `POST` link hủy → lần gửi sau `blocked:suppressed`; `GET` chỉ trả trang, không dòng chặn gửi.
- [ ] R3.6 (CP10): token sai chữ ký → 404, không dòng nào, cùng thân ở `GET` và `POST`; token đúng → `GET` 200, `POST` một dòng; `POST` lần hai → không dòng thứ hai.
- [ ] R3.7 (CP7): tin bị chặn có đúng một dòng nhật ký `blocked` với lý do, cùng giao dịch với audit.
- [ ] R3.8 (CP18): lượt gốc đã gửi tới 199 người nhận khác nhau → người thứ 200 gửi được; thêm tin tới người đã nhận không tính thêm; người thứ 201 → `blocked:recipient_cap`.
- [ ] R3.9 (CP24): dòng `dispatching` đã commit trước khi công cụ giả nhận lời gọi (kết nối thứ hai thấy dòng).
- [ ] R3.10 (CP24): lần gửi thứ hai tới cùng địa chỉ trong 24 giờ với khóa khác, kể cả khi lần đầu `outcome_unknown` hay ở workspace khác của cùng tenant → `blocked:frequency_cap`; hai lời gọi đồng thời tới cùng địa chỉ → đúng một `dispatching`.
- [ ] R3.11 (CP24): phát lại cùng khóa sau `outcome_unknown` → không dòng thứ hai, không bị tính vào trần; người nhận đã hủy giữa hai lần → `blocked:suppressed`; gỡ phép nhận ngay → test đỏ.
- [ ] R5.6 (CP19): `dw_app` DELETE một dòng chặn gửi của công ty `active` → 23514, dòng còn; lượt xóa offboarding xóa được; gọi `platform.purge_tenant_marketing` cho tenant `active` → lỗi, 0 dòng bị xóa.
- [ ] CP27: tenant B gửi tới địa chỉ có đồng ý ở tenant A → `blocked:no_consent`; token hủy của A gọi ở bất kỳ ngữ cảnh nào chỉ ghi dòng chặn gửi của A; B không đọc được dòng nhật ký, đồng ý hay chặn gửi của A.
- [ ] CP28: spec công cụ `external` thiếu `sends_message` → nạp lỗi; công cụ gửi tin có hai người nhận → `blocked:multiple_recipients`.
- [ ] CP29: `is_deployed` với `UNSUBSCRIBE_SIGNING_SECRET` 16 byte → API không khởi động.
- [ ] R3.7 (CP7): phát lại bị chặn vì người nhận đã hủy → một `marketing.send_refused` với `details.replay = true`, không dòng nhật ký thứ hai.
- [ ] R3.3: `Admission` nhận được mang `unsubscribe_url` ký đúng tenant, kênh, địa chỉ; công cụ thử nhận nó trong đầu vào.
- [ ] CP27: `dw_app` trong ngữ cảnh tenant B INSERT dòng `tenant_id` A vào ba bảng → WITH CHECK từ chối; `ConsentLedger.record` cho tenant A từ ngữ cảnh B → từ chối; hàm đếm khi `app.tenant_id` trống → lỗi.
- [ ] Xong: `make test-unit test-contract test-architecture && uv run pytest -m integration packages/python/dw_platform packages/python/dw_agent_runtime apps/api apps/worker` xanh.

## Nguồn

- `docs/adr/0124-marketing-messages-pass-a-platform-send-floor.md:1`; ticket 04 bước 1, 2, 5, 6; spec: R3, R5.6, CP7-CP10, CP18, CP19, CP24, CP27-CP29.

## Comments

- 2026-10-29 (agent, tạm theo ủy quyền): tách từ ticket 04 theo gate `checking-plan-readiness` của leadcare (CRITICAL: ADR-0124 (Accepted) đòi sàn trước tác động gửi đầu tiên ở mọi profile, kể cả người nhận thử), để lát Digital Worker gửi thư tới Mailpit mà không lách ADR. Ticket 04 chờ ticket này và giữ overlay, đối tượng Đồng ý và bước trong sổ bước của tools-and-skills/01. Nếu sai thì: gộp lại vào ticket 04 và leadcare/01 chờ ticket 04.
- 2026-10-29 (agent, tạm theo ủy quyền): đánh dấu gửi tin là trường `sends_message` cùng `message` của spec công cụ cho tới khi manifest connector của ADR-0116 (Accepted) có, rồi chuyển sang manifest. Nếu sai thì: chờ connections-and-vault cho manifest.
- 2026-10-29 (agent, tạm theo ủy quyền): theo gate `checking-plan-readiness` (2 CRITICAL, 5 HIGH): khung giờ cố định `Asia/Ho_Chi_Minh` (không đọc múi giờ công ty, vì đổi múi giờ là nới sàn); test âm chéo tenant cho ba bảng và token (CP27); hàm xóa từ chối tenant không `offboarding`; vị trí của sàn sau approval và phát lại; một người nhận mỗi lời gọi; trần tần suất của tenant qua hàm đếm; `sends_message` bắt buộc khai (CP28); phát lại vẫn kiểm chặn gửi và đồng ý; hủy nhận là trang `GET` và hành động `POST`; token mang tenant, không mang địa chỉ. Nếu sai thì: từng mục quay về bản trước trong lịch sử git.
- 2026-10-29 (agent, tạm theo ủy quyền): theo lượt xác nhận của gate (không CRITICAL mới): phát lại bị chặn chỉ ghi audit (R3.7 mới); ticket 04 thu về R3.5, R3.12; mọi trường địa chỉ khai trong `recipient_fields`; rate limit cho route hủy; `Admission` mang link hủy cho công cụ; trang xác nhận là trang web antd; token hết hạn 400 ngày; hàm đếm và hàm xóa RAISE khi thiếu hay lệch `app.tenant_id`; test ghi chéo tenant. Gate ĐẠT dựa trên lượt gate và lượt xác nhận.
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
