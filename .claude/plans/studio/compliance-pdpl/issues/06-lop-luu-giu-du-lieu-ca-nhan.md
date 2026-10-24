# 06 — Lớp lưu giữ cho kho dữ liệu cá nhân mới, bỏ dẫn Nghị định 13

Status: needs-triage
Blocked by: 04, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.7, R5.8, R5.9, CP16, CP17, CP20, CP22

## Mục tiêu

Mỗi kho dữ liệu cá nhân lát này thêm có một thời hạn và một bộ xóa đã đăng ký trong tệp chính sách retention,
theo định dạng khóa `schema.table` của telemetry-and-audit; hội thoại quá 90 ngày bị xóa qua một hàm hẹp không đối
số, hạn nằm trong thân hàm và khớp tệp retention, mà lane lưu giữ gọi và audit như chính lane; Danh sách chặn gửi
không bao giờ hết hạn theo thời gian; chú thích thời hạn dẫn Nghị định 356 thay Nghị định 13/2023 (spec R5;
ADR-0106 (Accepted), ADR-0123 (Accepted)).

## Việc cần làm

1. Một bản mới của tệp chính sách retention, bản cuối của chuỗi các ticket sửa tệp ở mục Phụ thuộc của spec, sau
   bản của agent-builder/04 (DO-52), số ghi UNVERIFIED tới khi luật sư xác nhận trước chạy bóng: bộ xóa theo dòng
   của Bản ghi đồng ý (thời hạn theo quan hệ cộng 5 năm mà ticket 04 đã thêm dưới khóa `platform.consent_records`;
   một hàm riêng của lane vì `dw_app` không DELETE bảng, không DROP PARTITION), khóa `platform.contact_suppressions`
   không hạn theo thời gian (bộ xóa là offboarding của công ty, lượt xóa duy nhất mà trigger của ticket 04 cho qua,
   spec R5.6, và, ở W2, yêu cầu của chủ thể dữ liệu), khóa `studio.conversations` 90 ngày (DO-52, Đạt 24/10/2026)
   cùng bộ xóa của hai bảng hội thoại, là hàm của bước 4, vì khóa `studio.conversation_messages` 90 ngày đã có từ
   agent-builder/04, đăng ký bộ xóa với lane lưu giữ của telemetry-and-audit. Nhật ký gửi marketing (13 tháng, DROP
   PARTITION) đã có khóa từ ticket 04; thời hạn của sự kiện vào Data Hub do workflow-triggers/02 thêm, lane của
   telemetry-and-audit thi hành.
2. Sửa chú thích thời hạn Nhật ký kiểm toán trong bản đó của tệp chính sách retention và
   `.claude/plans/ops-hardening.md:22` sang PDPL và Nghị định 356 (điều khoản do luật sư xác nhận), bỏ dẫn
   Nghị định 13/2023.
3. Test tập bộ xóa: mỗi lớp dữ liệu cá nhân có một bộ xóa đã đăng ký; một lớp thiếu bộ xóa → đỏ. Test riêng
   cho Danh sách chặn gửi: lane lưu giữ chạy qua một dòng chặn gửi 10 năm tuổi mà dòng còn (spec R5.4).
4. Migration (id hex ngẫu nhiên): hàm `studio.purge_expired_conversations()` SECURITY DEFINER, không đối số
   (search_path cố định; hạn 90 ngày nằm trong thân hàm, mốc `now() - interval '90 days'`; REVOKE ALL FROM PUBLIC rồi
   GRANT EXECUTE cho `dw_app`, vai mà lane lưu giữ của worker dùng), theo tiền lệ `platform.prune_notifications()`
   (`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:168-190`) và mẫu xóa dữ liệu hết hạn của
   ADR-0122 (Accepted) quyết 7, vì `dw_app` chỉ SELECT, INSERT trên `studio.conversation_messages`: ở mọi công ty, xóa
   dòng `studio.conversation_messages` có `created_at` trước mốc, rồi xóa dòng `studio.conversations` không còn tin
   nào và có `created_at` trước mốc, theo thứ tự đó vì FK ghép của tin nhắn tới `studio.conversations` là
   `ON DELETE RESTRICT` (agent-builder/04); không xóa gì khác; trả một dòng mỗi workspace có dòng bị xóa (`tenant_id`,
   `workspace_id`, số tin, số hội thoại), vì `lane_audit_event` đòi `workspace_id` và
   `platform.audit_events.workspace_id` là NOT NULL. Test ranh giới đọc thời hạn dưới khóa
   `studio.conversation_messages` và `studio.conversations` của bản tệp chính sách retention đang ghim và đỏ khi hai
   khóa khác nhau hay khi hàm không xóa đúng ở mốc đó, vì hạn trong thân hàm là bản sao thứ hai của thời hạn trong tệp
   (spec R5.9; `failure-modes.md` #2). Bộ xóa đăng ký với lane lưu giữ gọi hàm không đối số (spec R5.7) và, trong
   cùng giao dịch, ghi cho mỗi dòng trả về một sự kiện `studio.conversation.expired` dựng bằng `lane_audit_event`
   (công ty và workspace của dòng đó, actor `system_actor(<lane>)`, `details.actor` `system:<lane>`, `details` mang
   hai số) qua `lane_audit.append_across_tenants` (spec R5.8; ADR-0011 (Accepted));
   không ghi được sự kiện thì giao dịch lùi và không dòng nào bị xóa.

## Tiêu chí chấp nhận

- [ ] R5.1 (CP16): mỗi kho mới của lát (Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi marketing, hội thoại 90
      ngày) có một thời hạn dưới khóa của nó trong tệp chính sách retention đang ghim và một bộ xóa đã đăng ký; ca
      xóa hội thoại theo tuổi thử ở R5.7.
- [ ] R5.7 (CP20): hai công ty, mỗi công ty có tin 91 ngày và tin 89 ngày tuổi → một lượt lane xóa tin 91 ngày
      của cả hai, tin 89 ngày còn; hội thoại mà mọi tin quá 90 ngày bị xóa sau tin của nó; hội thoại còn một tin 89
      ngày giữ nguyên; hội thoại tạo 10 ngày trước chưa có tin giữ nguyên; `dw_app` DELETE thẳng một tin →
      `permission denied`; hàm bỏ điều kiện mốc → test đỏ.
- [ ] R5.8 (CP20): sau lượt đó, mỗi workspace có dòng bị xóa có đúng một sự kiện `studio.conversation.expired` ở
      đúng công ty và workspace đó, với actor `system_actor(<lane>)`, `details.actor` `system:<lane>` và đúng số tin,
      số hội thoại đã xóa ở workspace đó; làm hỏng ghi audit → giao dịch lùi, không dòng nào bị xóa.
- [ ] R5.9 (CP22): test đọc thời hạn dưới khóa `studio.conversation_messages` và `studio.conversations` của bản tệp
      chính sách retention đang ghim, tạo tin trước mốc đó một phút và sau mốc một phút, gọi hàm → tin trước mốc bị
      xóa, tin sau mốc còn; thân hàm giữ 60 ngày trong khi tệp ghi 90 → test đỏ, nêu khóa; hai khóa ghi hai thời hạn
      khác nhau → test đỏ.
- [ ] R5.2 (CP16): một kho dữ liệu cá nhân không có bộ xóa đăng ký → test tập bộ xóa đỏ.
- [ ] R5.3: chú thích thời hạn Nhật ký kiểm toán dẫn PDPL và Nghị định 356, không dẫn Nghị định 13/2023.
- [ ] R5.4 (CP17): dòng chặn gửi 10 năm tuổi còn sau một lượt lane lưu giữ, lần gửi sau vẫn
      `blocked:suppressed`; thêm hạn theo thời gian cho lớp chặn gửi → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `configs/policies/retention@1.7.0.yaml:118-120`; spec: R5.3 (dẫn Nghị định 13/2023 đã hết hiệu lực).
- `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:28-29`; spec: R5.7 (hàm xóa không nhận đối
  số, nên không bên gọi nào nới nó tới dòng còn hạn).
- `infra/compose/docker-compose.yml:432`; spec: R5.7 (worker, nơi lane lưu giữ chạy, nối PostgreSQL bằng `dw_app`,
  nên EXECUTE của hàm cấp cho `dw_app`).
- `packages/python/dw_platform/src/dw_platform/domain/audit.py:72`,
  `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:299`; spec: R5.8 (`lane_audit_event`
  đòi `workspace_id`, cột đó NOT NULL trên `platform.audit_events`).
- ADR-0106 (Accepted) quyết 7; ADR-0123 (Accepted) quyết 1; ADR-0122 (Accepted) quyết 7; ADR-0011 (Accepted).

## Comments

- 2026-10-23 (agent): B11-security compliance-pdpl 10. `needs-info` vì DO-52 (thời hạn mỗi kho) chờ counsel
  và Đạt. `retention@1.8.0` đồng sở hữu với telemetry-and-audit (lát đó giữ lớp run, Bước chạy, Sổ sử
  dụng); lát này thêm lớp đồng ý, gửi, sự kiện Data Hub.
- 2026-10-23 (agent): áp DO-52 (Đạt, 23/10/2026): telemetry-and-audit/03 là chủ bản 1.8.0, ticket này nâng
  lên 1.9.0 và chờ ticket đó (OPS-b); Danh sách chặn gửi giữ suốt quan hệ; sự kiện Data Hub chuyển sang
  telemetry-and-audit. Chờ ticket 04 và agent-builder/04 vì các kho của chúng là đối tượng của bộ xóa
  (I:agent-builder/04~compliance-pdpl/06). Còn `needs-info` vì DO-52 giao số tạm cho hội thoại cho Đạt mà sổ
  quyết định chưa ghi số.
- 2026-10-24 (agent): Đạt đặt số tạm cho hội thoại ngày 24/10/2026: 90 ngày, UNVERIFIED chờ luật sư khi có dữ
  liệu thật (DO-52; H:compliance-pdpl:R5.1\~requirements.md:419), nên `needs-triage`. Theo quyết định cùng ngày về
  tệp retention, thời hạn của Bản ghi đồng ý và nhật ký gửi vào ở ticket 04 cùng thay đổi đăng ký; ticket này
  đăng ký bộ xóa của Bản ghi đồng ý, thêm Danh sách chặn gửi và hội thoại, không ghi cứng số phiên bản tệp.
- 2026-10-24 (agent): theo dòng tạm cùng ngày của spec (C:configs:spec\~telemetry-and-audit/03), ticket này ra bản
  cuối của chuỗi các ticket sửa tệp retention, sau agent-builder/04, nên chỉ thêm khóa `studio.conversations`; khóa
  `studio.conversation_messages` đã vào ở agent-builder/04 cùng lúc đăng ký bảng. Thời hạn của sự kiện vào Data Hub
  do workflow-triggers/02 thêm (A:telemetry-and-audit:spec\~workflow-triggers/02).
- 2026-10-24 (agent): lượt sửa thứ hai của vòng 4, theo dòng tạm cùng ngày của spec: bộ xóa của hai bảng hội thoại
  là hàm SECURITY DEFINER hẹp `studio.purge_expired_conversations(p_cutoff timestamptz)` của bước 4, vì `dw_app` chỉ
  SELECT, INSERT trên tin nhắn và FK ghép của tin nhắn tới hội thoại là `ON DELETE RESTRICT` (agent-builder/04);
  lane lưu giữ audit như chính nó, mỗi workspace có dòng bị xóa một sự kiện kèm số dòng, vì một sự kiện audit luôn
  mang `workspace_id` (ADR-0011 (Accepted)); thêm R5.7, R5.8, CP20.
- 2026-10-24 (agent): lượt sửa thứ ba của vòng 4, theo dòng tạm cùng ngày của spec: hàm của bước 4 là
  `studio.purge_expired_conversations()` không đối số, hạn 90 ngày trong thân hàm, EXECUTE chỉ cho `dw_app` sau
  REVOKE ALL FROM PUBLIC, theo tiền lệ `platform.prune_notifications()`; lane gọi hàm không mốc; thêm R5.9 (CP22),
  test ranh giới đỏ khi hạn trong thân hàm khác thời hạn của hai khóa hội thoại trong tệp chính sách retention.
