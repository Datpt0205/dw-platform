# 04 — Sàn gửi tin marketing: đồng ý, chặn gửi, khung giờ, tần suất

Status: needs-triage
Blocked by: .claude/plans/studio/custom-objects/issues/03-record-service.md, .claude/plans/studio/tools-and-skills/issues/01-executor-kiem-schema-va-nha-may.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R5.1, R5.5, CP7, CP8, CP9, CP10, CP11, CP18

## Mục tiêu

Một Sàn gửi tin kiểm trong ToolExecutor so với các Bản ghi đồng ý của nền tảng: một tin marketing chỉ rời
đi khi không bị chặn, có đồng ý đúng mục đích và kênh, trong Khung giờ không gửi và dưới Giới hạn tần suất
gửi; hủy đăng ký có hiệu lực ngay (spec R3; ADR-0124 (Accepted)).

## Việc cần làm

1. Migration (id hex ngẫu nhiên):
    - `platform.consent_records`: chỉ thêm, bảng toàn tenant (RLS chỉ theo công ty, không `workspace_id`);
      phân vùng theo tháng trên `captured_at` với DEFAULT, đăng ký bằng một dòng
      `platform.time_partitioned_tables` (`append_only = true`); `subject_ref`, `purpose` CHECK (`marketing`,
      `transactional`), `channel` CHECK (`zns`, `email`, `sms`, `messenger`, `zalo_oa`), `state`,
      `captured_at`, `source`, `evidence_ref`, `notice_version`, `withdrawn_at`; index `(tenant_id,
subject_ref, channel, purpose, captured_at DESC)`; đồng ý hiện hành là dòng mới nhất theo
      `(subject_ref, purpose, channel)`, nên một lần rút ghi ở workspace nào cũng chặn ở mọi workspace.
    - `platform.contact_suppressions`: PK `(tenant_id, channel, address_hash)`; bảng toàn tenant (RLS chỉ
      theo công ty).
    - `platform.marketing_send_log`: phân vùng tháng, đăng ký bằng một dòng `platform.time_partitioned_tables`
      (`append_only = true`); RLS dạng workspace của `CLAUDE.md` trên bảng cha; một dòng mỗi Tương tác ở W1
      (N4): `outcome` CHECK (`sent`, `blocked`), `blocked_reason` (NULL khi `sent`, CHECK theo tập lý do của
      bước 2), `root_run_id`, `consent_record_id` khi `sent`, nguồn gốc tin AI soạn (lượt chạy soạn, model).
    - `dw_app` không giữ quyền nào trên partition nào của hai bảng phân vùng, kể cả DEFAULT; đọc ghi qua
      bảng cha (DO-02.2), không DELETE trên cha. `consent_records` và `contact_suppressions` có tên và lý do trong
      danh sách bảng toàn tenant của `test_rls_coverage.py`; `contact_suppressions` có DELETE cho `dw_app` để lane
      `offboarding` xóa như bảng thường.
    - Cùng thay đổi đăng ký: khóa `platform.consent_records` (theo quan hệ cộng 5 năm, xóa theo dòng; bộ xóa đăng
      ký ở ticket 06) và `platform.marketing_send_log` (13 tháng, DROP PARTITION qua
      `platform.drop_expired_partitions`), số tạm UNVERIFIED, vào bản kế tiếp của tệp chính sách retention theo
      định dạng của telemetry-and-audit:R5.6, nên studio-skeleton:R3.7 xanh ngay khi đăng ký (spec R5.1); hai dòng
      `STUDIO_EXCLUSIONS` cho hai bảng với lý do "`dw_app` không DELETE; xóa khi offboarding bằng
      `platform.purge_tenant_append_only`" (spec R5.5; studio-skeleton:R4.3).
2. `MarketingSendPolicy` thỏa `SendAdmissionPort` của ToolExecutor; thứ tự kiểm: chặn gửi, đồng ý, tần
   suất, khung giờ (đọc múi giờ của công ty), rồi số người nhận khác nhau đã gửi trong lượt chạy gốc (đếm dòng
   `sent` của nhật ký gửi theo `root_run_id`; spec R3.8); trả `blocked:<lý do>` với lý do `suppressed`,
   `no_consent`, `consent_withdrawn`, `frequency_cap`, `quiet_hours`, `recipient_cap`.
3. ToolExecutor hỏi `SendAdmissionPort` trên mọi hành động connector mà manifest đánh dấu là gửi tin,
   trước khi egress client gửi; không node nào kiểm thay (ADR-0112 (Accepted) quyết 6).
4. `configs/policies/marketing_send@1.0.0.yaml`: số mặc định thận trọng ghi UNVERIFIED (1 tin mỗi địa chỉ
   mỗi kênh mỗi 24 giờ, 08:00-20:00 Asia/Ho_Chi_Minh, tối đa 200 người nhận mỗi lượt chạy ở thí điểm; DO-55,
   Đạt 24/10/2026); overlay công ty chỉ siết, lỏng hơn (kể cả số người nhận cao hơn) → 422.
5. Route công khai `GET /api/v1/public/unsubscribe/{token}`: HMAC một địa chỉ, rate-limited, idempotent,
   không lộ địa chỉ có tồn tại; ghi một dòng chặn gửi trong 5 phút. Từ khóa hủy trên Zalo qua inbound router
   là W2 (router sự kiện nhà cung cấp và kênh Zalo là W2).
6. Audit `marketing.sent` (kèm `consent_record_id`), `marketing.send_refused` (lý do); chỉ ticket này ghi
   `marketing.send_refused`, trong giao dịch của executor, cùng một dòng nhật ký gửi `outcome` `blocked` kèm lý do
   (spec R3.7); ToolExecutor của tools-and-skills/01 chỉ trả kết quả bị chặn kèm lý do.

## Tiêu chí chấp nhận

- [ ] R3.1 (CP7): lead không có Bản ghi đồng ý đúng mục đích và kênh → `blocked:no_consent`, 0 tin,
      `marketing.send_refused`; gỡ kiểm → test đỏ.
- [ ] R3.7 (CP7): cùng lần chặn đó ghi đúng một dòng nhật ký gửi `outcome` `blocked`, `blocked_reason`
      `no_consent`, trong cùng giao dịch với `marketing.send_refused`; rollback giao dịch → không dòng nào.
- [ ] R3.8 (CP18): một lượt chạy gốc đã gửi tới 200 người nhận khác nhau, tin tới người thứ 201 →
      `blocked:recipient_cap`, SMTP giả 0 lời gọi; tin thứ hai tới một người đã nhận trong lượt đó không tính thêm
      người nhận; overlay hạ còn 50 → người thứ 51 bị chặn; gỡ kiểm → test đỏ.
- [ ] R5.1: đăng ký `consent_records` và `marketing_send_log` → test catalog của studio-skeleton:R3.7 xanh vì hai
      khóa đã có trong bản tệp của thay đổi này; bỏ một khóa → test đó đỏ, nêu tên bảng.
- [ ] R5.5: công ty `offboarding` có dòng trong ba bảng → lane `offboarding` xuất mỗi dòng một lần rồi xóa hết;
      test phủ offboarding (studio-skeleton:R4.3) xanh với hai dòng `STUDIO_EXCLUSIONS`.
- [ ] R3.2 (CP8): gọi hành động gửi qua node `tool.call`, qua công cụ agent, qua quy trình-như-công-cụ khi
      thiếu đồng ý → cả ba bị chặn ở executor; gỡ kiểm ở executor → test đỏ.
- [ ] R3.3: một tin rời đi → một dòng nhật ký gửi mang `consent_record_id` và một sự kiện `marketing.sent`.
- [ ] R3.4 (CP9): bấm link hủy → lần gửi sau `blocked:suppressed` trong ≤ 5 phút; một tin đang chờ bị kiểm
      lại trước khi gửi; rút đồng ý ghi ở workspace Sales chặn tin từ workspace Marketing.
- [ ] R3.5 (CP11): overlay đặt Giới hạn tần suất gửi, Khung giờ không gửi hay số người nhận mỗi lượt (300) lỏng
      hơn sàn → 422, không nhận overlay; overlay đặt 50 người nhận → nhận; gửi lần hai trong 24 giờ →
      `blocked:frequency_cap`; ngoài khung giờ → `blocked:quiet_hours`.
- [ ] R3.6 (CP10): `GET /api/v1/public/unsubscribe/{token}` với token sai chữ ký HMAC → 404, không dòng
      nào, không lộ địa chỉ có tồn tại.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `db/migrations/versions/5a25154e0296_platform_channel_deliveries.py:125-132`; spec: R3.2 (đường gửi chỉ
  tới thành viên hiện tại; lead là đường connector qua executor).
- ADR-0124 (Accepted) quyết 1, 2, 4, 5, 6.

## Comments

- 2026-10-23 (agent): gộp B11-security compliance-pdpl 04 và phần đồng ý của B12-product marketing-pilot 08. `needs-info` vì DO-55 (số chống spam, lời văn đồng ý người nhận thử) chờ luật sư; số giữ UNVERIFIED.
  Sổ đồng ý là của nền tảng; object Consent của gói Marketing là view đọc.
- 2026-10-23 (agent): DO-55 có lời đáp cho W1 (Đạt, 23/10/2026: số tạm UNVERIFIED), nên `needs-triage`. Áp
  E:CLAUDE.md#tenancy-and-authorization~compliance-pdpl:platform.consent_records (a) và ADR-0124 (Accepted):
  đồng ý và chặn gửi toàn tenant, nhật ký gửi hình workspace; DO-02.2 cho partition; từ khóa hủy Zalo sang W2.
  Số người nhận tối đa mỗi lượt mà ADR-0124 (Accepted) quyết 6 khai chưa có số tạm, nên bước 4 chưa đặt nó.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: DO-55 có số tạm (200 người nhận mỗi lượt ở thí điểm,
  công ty chỉ hạ), bước 4 đặt nó và bước 2 đọc nó (`blocked:recipient_cap`, spec R3.8), nên `needs-triage` giữ
  nguyên (H:ADR-0124 (Accepted)\~compliance-pdpl/04); mỗi lần chặn ghi một dòng nhật ký gửi `blocked` vì ở W1 Tương
  tác là dòng nhật ký gửi (N4); thêm thời hạn của hai bảng `append_only` trong cùng thay đổi đăng ký và chờ
  telemetry-and-audit/03 để các ticket sửa tệp retention có một thứ tự; dòng `STUDIO_EXCLUSIONS` cho offboarding.
