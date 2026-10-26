# 06 — Lớp lưu giữ cho kho dữ liệu cá nhân mới, bỏ dẫn Nghị định 13

Status: needs-triage
Blocked by: 04, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.7, R5.8, R5.9, R5.10, CP16, CP17, CP20, CP22, CP23

## Mục tiêu

Mỗi kho dữ liệu cá nhân lát này thêm có một thời hạn và một bộ xóa đã đăng ký trong mảnh retention của kho đó,
theo định dạng mảnh của telemetry-and-audit (H-1); hội thoại quá 90 ngày bị xóa qua một hàm hẹp không đối
số, đọc hạn ở `platform.retention_terms` thay cho một hằng trong thân hàm (V4.21), mà lane lưu giữ gọi và audit như
chính lane; Bản ghi đồng ý quá hạn bị xóa qua một hàm hẹp cùng cách; Danh sách chặn gửi không bao giờ hết hạn theo
thời gian; chú thích thời hạn dẫn Nghị định 356 thay Nghị định 13/2023 (spec R5; ADR-0106 (Accepted),
ADR-0123 (Accepted)).

## Việc cần làm

1. Mảnh retention theo định dạng của telemetry-and-audit/01 (H-1; DO-52), số ghi UNVERIFIED tới khi luật sư xác nhận
   trước chạy bóng, trong cùng thay đổi đăng ký bộ xóa, không chờ ticket nào chỉ vì thứ tự tệp: bộ xóa theo dòng của
   Bản ghi đồng ý (thời hạn theo quan hệ cộng 5 năm trong mảnh `platform.consent_records` mà ticket 04 đã thêm; một hàm
   SECURITY DEFINER hẹp không đối số của lane vì `dw_app` không DELETE bảng, không DROP PARTITION, đọc hạn dưới khóa
   đó qua `platform.retention_term_days` của telemetry-and-audit/01 và không giữ hằng nào, spec R5.9, R5.10; REVOKE ALL
   FROM PUBLIC rồi GRANT EXECUTE cho `dw_app` như hàm của bước 4); mảnh
   `configs/policies/retention.d/platform.contact_suppressions.yaml` với `days: indefinite`, `purger: none`,
   `enforced: true` và `description` nói kho không hết hạn theo thời gian (H-31; `null` nghĩa là chưa ai quyết) (bộ xóa là offboarding của công ty, lượt xóa duy nhất mà trigger
   của ticket 04 cho qua, spec R5.6, và, ở W2, yêu cầu của chủ thể dữ liệu; spec R5.4); mảnh
   `configs/policies/retention.d/studio.conversations.yaml` với `days: 90` (DO-52, Đạt 24/10/2026), `purger:
row_delete`, `enforced: true`, cùng bộ xóa của hai bảng hội thoại, là hàm của bước 4, và đổi mảnh
   `studio.conversation_messages` 90 ngày mà agent-builder/04 thêm với `enforced: false` thành `enforced: true` trong cùng
   thay đổi, vì bộ xóa của nó ra đời ở đây; đăng ký bộ xóa với lane lưu giữ của
   telemetry-and-audit/03. Nhật ký gửi marketing (13 tháng, DROP PARTITION) đã có mảnh từ ticket 04; thời hạn của sự
   kiện vào Data Hub do workflow-triggers/02 thêm, lane của telemetry-and-audit thi hành.
2. Sửa chú thích căn cứ pháp lý của thời hạn Nhật ký kiểm toán trong mảnh
   `configs/policies/retention.d/platform.audit_events.yaml` mà telemetry-and-audit/01 tạo (chỉ trường `description`,
   không đổi `days`, không sửa tệp có phiên bản `retention@1.8.0.yaml` nào; H-1) và
   `.claude/plans/ops-hardening.md:22` sang PDPL và Nghị định 356 (điều khoản do luật sư xác nhận), bỏ dẫn
   Nghị định 13/2023.
3. Test tập bộ xóa: mỗi lớp dữ liệu cá nhân có một bộ xóa đã đăng ký; một lớp thiếu bộ xóa → đỏ. Test riêng
   cho Danh sách chặn gửi: lane lưu giữ chạy qua một dòng chặn gửi 10 năm tuổi mà dòng còn (spec R5.4).
4. Migration (id hex ngẫu nhiên): hàm `studio.purge_expired_conversations()` SECURITY DEFINER, không đối số
   (search_path cố định; REVOKE ALL FROM PUBLIC rồi GRANT EXECUTE cho `dw_app`, vai mà lane lưu giữ của worker dùng),
   theo tiền lệ `platform.prune_notifications()`
   (`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:168-190`) và mẫu xóa dữ liệu hết hạn của
   ADR-0122 (Accepted) quyết 7, vì `dw_app` chỉ SELECT, INSERT trên `studio.conversation_messages`. Hàm không giữ hằng
   thời hạn nào: nó gọi `platform.retention_term_days` của telemetry-and-audit/01 cho khóa
   `studio.conversation_messages` và `studio.conversations`, báo lỗi và không xóa gì khi một khóa thiếu dòng hay hai
   hạn khác nhau (spec R5.10; V4.21), rồi đặt mốc bằng `now()` trừ hạn đó (spec R5.9). Ở mọi công ty, xóa dòng
   `studio.conversation_messages` có `created_at` trước mốc, rồi xóa dòng `studio.conversations` không còn tin nào và
   có `created_at` trước mốc, theo thứ tự đó vì FK ghép của tin nhắn tới `studio.conversations` là
   `ON DELETE RESTRICT` (agent-builder/04); không xóa gì khác; trả một dòng mỗi workspace có dòng bị xóa (`tenant_id`,
   `workspace_id`, số tin, số hội thoại), vì `lane_audit_event` đòi `workspace_id` và
   `platform.audit_events.workspace_id` là NOT NULL. Test ranh giới đọc thời hạn ở `platform.retention_terms`, bảng mà
   bộ nạp của telemetry-and-audit/01 nạp từ tập mảnh retention đang ghim, và đỏ khi hàm không xóa đúng ở mốc
   đó hay khi hàm giữ một hằng thay cho hạn của bảng (spec R5.9); bảng lệch tệp là việc của test lệch bảng của
   telemetry-and-audit (telemetry-and-audit:R5.10). Bộ xóa đăng ký với lane lưu giữ gọi hàm không đối số (spec
   R5.7) và, trong cùng giao dịch, ghi cho mỗi dòng trả về một sự kiện `studio.conversation.expired` dựng bằng
   `lane_audit_event` (công ty và workspace của dòng đó, actor `system_actor(<lane>)`, `details.actor`
   `system:<lane>`, `details` mang hai số) qua `lane_audit.append_across_tenants` (spec R5.8; ADR-0011 (Accepted));
   không ghi được sự kiện thì giao dịch lùi và không dòng nào bị xóa.

## Tiêu chí chấp nhận

- [ ] R5.1 (CP16): mỗi kho mới của lát (Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi marketing, hội thoại 90
      ngày) có một mảnh mang tên của nó trong tập mảnh retention đang ghim, với một thời hạn và một bộ xóa đã đăng
      ký; ca xóa hội thoại theo tuổi thử ở R5.7; gỡ mảnh `studio.conversations` hay `platform.contact_suppressions` →
      test phủ mảnh của telemetry-and-audit/01 đỏ, nêu tên bảng.
- [ ] R5.7 (CP20): hai công ty, mỗi công ty có tin 91 ngày và tin 89 ngày tuổi → một lượt lane xóa tin 91 ngày
      của cả hai, tin 89 ngày còn; hội thoại mà mọi tin quá 90 ngày bị xóa sau tin của nó; hội thoại còn một tin 89
      ngày giữ nguyên; hội thoại tạo 10 ngày trước chưa có tin giữ nguyên; `dw_app` DELETE thẳng một tin →
      `permission denied`; hàm bỏ điều kiện mốc → test đỏ.
- [ ] R5.8 (CP20): sau lượt đó, mỗi workspace có dòng bị xóa có đúng một sự kiện `studio.conversation.expired` ở
      đúng công ty và workspace đó, với actor `system_actor(<lane>)`, `details.actor` `system:<lane>` và đúng số tin,
      số hội thoại đã xóa ở workspace đó; làm hỏng ghi audit → giao dịch lùi, không dòng nào bị xóa.
- [ ] R5.9 (CP22): test đọc thời hạn dưới khóa `studio.conversation_messages` của `platform.retention_terms`, tạo
      tin trước mốc đó một phút và sau mốc một phút, gọi hàm → tin trước mốc bị xóa, tin sau mốc còn; đặt hai dòng
      hội thoại của bảng thử thành 60 ngày → tin 61 ngày bị xóa, tin 59 ngày còn; thân hàm giữ hằng 90 ngày → test
      đỏ; đổi hạn của `platform.consent_records` trong bảng thử → mốc của bộ xóa Bản ghi đồng ý đổi theo; bộ xóa đó
      giữ hằng 5 năm → test đỏ.
- [ ] R5.10 (CP23): xóa dòng `studio.conversations` khỏi bảng thử → `studio.purge_expired_conversations()` báo lỗi,
      không tin hay hội thoại nào bị xóa; hai dòng hội thoại 90 và 120 → báo lỗi, không dòng nào bị xóa; xóa dòng
      `platform.consent_records` → bộ xóa Bản ghi đồng ý báo lỗi, không dòng nào bị xóa; hàm dùng hạn mặc định khi
      thiếu dòng → test đỏ.
- [ ] R5.2 (CP16): một kho dữ liệu cá nhân không có bộ xóa đăng ký → test tập bộ xóa đỏ.
- [ ] R5.3: `description` của mảnh `platform.audit_events` dẫn PDPL và Nghị định 356, không dẫn Nghị định 13/2023;
      `days` của mảnh không đổi; một test quét tập mảnh thấy chuỗi "13/2023" → đỏ.
- [ ] R5.4 (CP17): dòng chặn gửi 10 năm tuổi còn sau một lượt lane lưu giữ, lần gửi sau vẫn
      `blocked:suppressed`; thêm hạn theo thời gian cho lớp chặn gửi → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `configs/policies/retention@1.7.0.yaml:118-120`; spec: R5.3 (dẫn Nghị định 13/2023 đã hết hiệu lực; telemetry-and-audit/01
  bước 10 chép chú thích đó sang mảnh `platform.audit_events`, mà ticket này sửa).
- `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:28-29`; spec: R5.7 (hàm xóa không nhận đối
  số, nên không bên gọi nào nới nó tới dòng còn hạn).
- `infra/compose/docker-compose.yml:432`; spec: R5.7 (worker, nơi lane lưu giữ chạy, nối PostgreSQL bằng `dw_app`,
  nên EXECUTE của hàm cấp cho `dw_app`).
- `packages/python/dw_platform/src/dw_platform/domain/audit.py:72`,
  `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:299`; spec: R5.8 (`lane_audit_event`
  đòi `workspace_id`, cột đó NOT NULL trên `platform.audit_events`).
- ADR-0106 (Accepted) quyết 7; ADR-0123 (Accepted) quyết 1; ADR-0122 (Accepted) quyết 7; ADR-0011 (Accepted).
- telemetry-and-audit:R5.9, telemetry-and-audit:R5.10, telemetry-and-audit:R5.12; spec: R5.9, R5.10 (bảng thời hạn,
  test lệch bảng và hàm đọc hạn mà hai hàm xóa hẹp của ticket này gọi; V4.21).

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
- 2026-10-24 (agent): lượt f của vòng 4, theo V4.21 của Đạt và dòng tạm cùng ngày của spec: hai hàm xóa hẹp của
  ticket này (hội thoại ở bước 4, Bản ghi đồng ý ở bước 1) vẫn không đối số nhưng không còn giữ hằng thời hạn: chúng
  đọc hạn ở `platform.retention_terms` qua `platform.retention_term_days` của telemetry-and-audit/03, ticket mà ticket
  này đã chờ, nên không cần cạnh mới; R5.9 (CP22) nay thử việc đọc hạn từ bảng, R5.10 (CP23) thử việc từ chối khi
  thiếu dòng hay hai hạn hội thoại khác nhau; luật sư đổi số bằng một bản mới của tệp mà bộ nạp nạp lúc triển khai,
  không bằng migration.
- 2026-10-25 (agent): lượt h, theo H-1 và bảng cạnh của lượt: chính sách lưu giữ là một mảnh mỗi kho dưới
  `configs/policies/retention.d/`, nên bước 1 thêm mảnh của Danh sách chặn gửi và `studio.conversations` thay một bản
  mới của tệp có phiên bản, và bước 2 sửa chú thích căn cứ pháp lý trong mảnh `platform.audit_events` mà
  telemetry-and-audit/01 tạo, không sửa tệp có phiên bản; bộ nạp, `platform.retention_terms` và
  `platform.retention_term_days` nay ở telemetry-and-audit/01, nên thêm Blocked by ticket đó; telemetry-and-audit/03
  (lane lưu giữ, đăng ký bộ xóa) giữ.
