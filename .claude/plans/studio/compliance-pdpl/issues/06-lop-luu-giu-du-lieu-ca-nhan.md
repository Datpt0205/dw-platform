# 06 — Lớp lưu giữ cho kho dữ liệu cá nhân mới, bỏ dẫn Nghị định 13

Status: ready-for-agent
Blocked by: 04, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.7, R5.8, R5.9, R5.10, R5.11, CP16, CP17, CP20, CP22, CP23, CP30

## Mục tiêu

Mỗi kho dữ liệu cá nhân lát này thêm có một thời hạn và một bộ xóa đã đăng ký trong mảnh retention của kho đó,
theo định dạng mảnh của telemetry-and-audit (H-1); hội thoại quá 90 ngày bị xóa qua một hàm hẹp không đối
số, đọc hạn ở `platform.retention_terms` thay cho một hằng trong thân hàm (V4.21), mà lane lưu giữ gọi và audit như
chính lane; Bản ghi đồng ý quá hạn bị xóa qua một hàm hẹp cùng cách; Danh sách chặn gửi không bao giờ hết hạn theo
thời gian; chú thích thời hạn dẫn Nghị định 356 thay Nghị định 13/2023 (spec R5; ADR-0106 (Accepted),
ADR-0123 (Accepted)).

## Việc cần làm

1. Mảnh retention theo định dạng của telemetry-and-audit/01 (H-1; DO-52), số ghi UNVERIFIED tới khi luật sư xác nhận
   trước chạy bóng, trong cùng thay đổi đăng ký bộ xóa, không chờ ticket nào chỉ vì thứ tự tệp. Ba bộ xóa và ba mảnh:
    - Bản ghi đồng ý (spec R5.11): hàm `platform.purge_expired_consent_records()` SECURITY DEFINER, không đối số,
      search_path cố định, REVOKE ALL FROM PUBLIC rồi GRANT EXECUTE cho `dw_app` như hàm của bước 4, vì `dw_app` không
      DELETE bảng và bảng không xóa bằng DROP PARTITION (ADR-0124 (Accepted): "the row in force may be old"). "Hết quan
      hệ" của một bộ `(tenant_id, subject_ref, purpose, channel)` là lúc dòng mới nhất của bộ đó là `withdrawn`; hàm đọc
      dòng mới nhất theo đúng thứ tự mà sàn đọc đồng ý hiện hành (`captured_at` giảm dần, cùng thời điểm thì `withdrawn`
      trước; `packages/python/dw_platform/src/dw_platform/adapters/persistence/marketing_send_repo.py:49`), và một test
      đỏ khi sàn và bộ xóa chọn hai dòng khác nhau cho cùng một bộ; `withdrawn_at` NOT NULL đúng khi `withdrawn`
      (CHECK `ck_consent_records_withdrawn` của ticket 08). Hàm đọc
      hạn dưới khóa `platform.consent_records` qua `platform.retention_term_days` của telemetry-and-audit/01, không giữ
      hằng (spec R5.9, R5.10), đặt mốc bằng `now()` trừ hạn, rồi xóa mọi dòng của mỗi bộ mà dòng mới nhất là `withdrawn`
      với `withdrawn_at` trước mốc; bộ mà dòng mới nhất là `granted` giữ nguyên mọi dòng, dù cũ đến đâu, vì quan hệ còn
      và tin gửi dựa vào nó; gom và xóa theo bộ có `tenant_id` (hàm chạy ngoài RLS); bỏ qua công ty `offboarding` (lượt
      xóa của offboarding là của nó, ticket 08). Trả một dòng mỗi công ty có dòng bị xóa (`tenant_id`, `workspace_id` của
      workspace cũ nhất của công ty, do chính hàm tìm vì nó thấy qua RLS, số dòng); công ty không có workspace nào thì hàm
      không xóa dòng nào của nó. Hạn của mảnh này không ngắn hơn hạn của hai kho dẫn `consent_record_id` tới nó (nhật ký gửi,
      Nhật ký kiểm toán), để chuỗi "tin này dựa vào đồng ý nào" không đứt; một test so ba mảnh. Bộ xóa đăng ký ở `build_retention_purgers`
      (`apps/worker/src/dw_worker/main.py:341`) và, trong cùng giao dịch, lane `retention` ghi cho mỗi dòng trả về một sự
      kiện `consent.expired` dựng bằng `lane_audit_event` (actor `system_actor("retention")`, `details.actor`
      `system:retention`, `details` mang số dòng và mốc, `resource_type` `consent_records`, `resource_id` là
      `tenant_id`) qua `lane_audit.append_across_tenants`, vì Bản ghi đồng ý là điều một người đã làm, không phải dọn dẹp
      (`CLAUDE.md` mục 'Agent and tool rules'; ADR-0011 (Accepted)); bảng toàn tenant không có `workspace_id` mà
      `platform.audit_events.workspace_id` là NOT NULL, nên sự kiện đứng ở workspace cũ nhất của công ty (`created_at`
      nhỏ nhất của `platform.workspaces`, kể cả đã lưu trữ). Mảnh `platform.consent_records.yaml` mà ticket 08 thêm đổi
      `enforced: false` thành `true` và chú thích nêu luật "hết quan hệ" ở trên, trong cùng thay đổi.
    - Danh sách chặn gửi: mảnh `configs/policies/retention.d/platform.contact_suppressions.yaml` với `days: indefinite`,
      `purger: none`, `enforced: true` và `description` nói kho không hết hạn theo thời gian (H-31; `null` nghĩa là chưa
      ai quyết; bộ nạp chỉ nhận `indefinite` đi cùng `none`,
      `packages/python/dw_platform/src/dw_platform/retention_policy.py:167`); bộ xóa là offboarding của công ty, lượt xóa
      duy nhất mà trigger của ticket 08 cho qua (spec R5.6), và, ở W2, yêu cầu của chủ thể dữ liệu (spec R5.4).
    - Hội thoại: mảnh `configs/policies/retention.d/studio.conversations.yaml` với `days: 90` (DO-52, Đạt 24/10/2026),
      `purger: row_delete`, `enforced: true`, cùng bộ xóa của hai bảng hội thoại là hàm của bước 4, và đổi mảnh
      `studio.conversation_messages` 90 ngày mà agent-builder/04 thêm với `enforced: false` thành `enforced: true` trong
      cùng thay đổi, vì bộ xóa của nó ra đời ở đây; đăng ký ở `build_retention_purgers`.

    Nhật ký gửi marketing (spec R5.1; quyết định thuộc lát này, usage-and-limits/02 Comments 2026-11-04): mảnh
    `platform.marketing_send_log.yaml` mà ticket 08 thêm đổi `enforced: false` thành `true`, giữ `days: 395`, `purger:
drop_partition`; `platform.drop_expired_partitions` của usage-and-limits/02 đã đọc mốc của mọi bảng trong sổ từ mảnh
    `enforced: true`, nên không sửa hàm nào. DROP PARTITION không lùi được, và ở W1 chỉ có dữ liệu giả lập (YC89), nên
    bật bây giờ không mất dữ liệu thật; số 13 tháng do luật sư xác nhận trước khi dữ liệu thật vào (ticket 02). Thời hạn
    của sự kiện vào Data Hub do workflow-triggers/02 thêm, lane của telemetry-and-audit thi hành.

2. Thêm căn cứ pháp lý của thời hạn Nhật ký kiểm toán vào mảnh `configs/policies/retention.d/platform.audit_events.yaml`
   mà telemetry-and-audit/01 tạo (trường `description` và chú thích đầu tệp, nơi tệp để dành cho ticket này ở dòng 3-5;
   không đổi `days`, không sửa tệp có phiên bản `retention@1.8.0.yaml` nào; H-1): PDPL và Nghị định 356 (điều khoản do
   luật sư xác nhận); và sửa `.claude/plans/ops-hardening.md:22`, chỗ duy nhất còn dẫn Nghị định 13/2023.
3. Test tập bộ xóa: `test_every_purged_fragment_has_its_purger` (`apps/worker/tests/unit/test_worker.py:226`) đã giữ
   mọi mảnh `row_delete` `enforced` với một bộ xóa đăng ký (spec R5.2); ticket này thêm vào cùng test: một mảnh
   `purger: none` chỉ được nhận khi bảng của nó có trong một danh sách miễn có lý do, hôm nay chỉ
   `platform.contact_suppressions`; và bốn kho của lát (Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi marketing, hai
   bảng hội thoại) có mảnh `enforced: true`. Test riêng cho Danh sách chặn gửi: lane lưu giữ chạy qua một dòng chặn gửi
   10 năm tuổi mà dòng còn (spec R5.4). Một test quét nguồn đỏ khi một mô-đun ngoài bộ xóa của lane `retention` gọi
   `studio.purge_expired_conversations()` hay `platform.purge_expired_consent_records()`, vì EXECUTE của `dw_app` cũng
   tới tay API, và audit nằm ở lane (`failure-modes.md` #5).
4. Migration (id hex ngẫu nhiên): hàm `studio.purge_expired_conversations()` SECURITY DEFINER, không đối số
   (search_path cố định; REVOKE ALL FROM PUBLIC rồi GRANT EXECUTE cho `dw_app`, vai mà lane lưu giữ của worker dùng),
   theo tiền lệ `platform.prune_notifications()`
   (`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:168-190`) và mẫu xóa dữ liệu hết hạn của
   ADR-0122 (Accepted) quyết 7, vì `dw_app` chỉ SELECT, INSERT trên `studio.conversation_messages`. Hàm không giữ hằng
   thời hạn nào: nó gọi `platform.retention_term_days` của telemetry-and-audit/01 cho khóa
   `studio.conversation_messages` và `studio.conversations`, báo lỗi và không xóa gì khi một khóa thiếu dòng hay hai
   hạn khác nhau (spec R5.10; V4.21), rồi đặt mốc bằng `now()` trừ hạn đó (spec R5.9). Ở mọi công ty, xóa dòng
   `studio.conversation_messages` có `created_at` trước mốc, rồi xóa dòng `studio.conversations` không còn tin nào, có
   `created_at` trước mốc và `active_run_id` NULL, bỏ qua công ty `offboarding` như bộ xóa Bản ghi đồng ý, và bỏ qua dòng
   còn bị một FK của bảng khác dẫn tới (một test đọc `pg_constraint` đỏ khi có FK mới tới hai bảng mà hàm không xét), theo thứ tự đó vì FK ghép của tin nhắn tới `studio.conversations` là
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
- [ ] R5.11 (CP30): một bộ có dòng mới nhất `granted` từ 6 năm trước → còn mọi dòng sau một lượt lane; một bộ có dòng
      mới nhất `withdrawn` với `withdrawn_at` 5 năm và 1 ngày trước → mọi dòng của bộ bị xóa; `withdrawn_at` 4 năm trước
      → còn; công ty `offboarding` có bộ quá hạn → hàm không xóa dòng của nó; mỗi công ty có dòng bị xóa có đúng một sự
      kiện `consent.expired` ở workspace cũ nhất của công ty, actor `system_actor("retention")`, đúng số dòng; làm hỏng
      ghi audit → không dòng nào bị xóa; hàm xóa theo `captured_at` thay cho luật "hết quan hệ" → ca `granted` 6 năm
      đỏ. Hai công ty cùng `(subject_ref, purpose, channel)`: ở A dòng mới nhất `withdrawn` quá hạn, ở B `granted` → dòng
      của B còn, sự kiện chỉ ở A; gom bộ thiếu `tenant_id` → test đỏ. Một `granted` và một `withdrawn` cùng
      `captured_at` → sàn và bộ xóa cùng đọc `withdrawn`.
- [ ] R5.1 (CP16): mảnh `platform.marketing_send_log` `enforced: true` → một lượt lane `partitions` drop tháng nằm trọn
      trước 395 ngày, giữ tháng chứa mốc và mọi tháng sau; đặt lại `enforced: false` → không tháng nào bị drop.
- [ ] R5.2 (CP16): mảnh `purger: none` của một bảng ngoài danh sách miễn → test tập bộ xóa đỏ, nêu tên bảng; mảnh của
      một trong bốn kho của lát `enforced: false` → đỏ; một mô-đun của API gọi `studio.purge_expired_conversations()`
      hay `platform.purge_expired_consent_records()` → test quét nguồn đỏ; hạn của mảnh Bản ghi đồng ý ngắn hơn hạn của
      nhật ký gửi hay Nhật ký kiểm toán → đỏ.
- [ ] R5.7 (CP20): hội thoại có tin 91 ngày và tin 89 ngày → tin 91 ngày bị xóa, dòng hội thoại và tin 89 ngày còn.
- [ ] R5.3: `description` của mảnh `platform.audit_events` dẫn PDPL và Nghị định 356, không dẫn Nghị định 13/2023;
      `days` của mảnh không đổi; một test quét tập mảnh thấy chuỗi "13/2023" → đỏ.
- [ ] R5.4 (CP17): dòng chặn gửi 10 năm tuổi còn sau một lượt lane lưu giữ, lần gửi sau vẫn
      `blocked:suppressed`; thêm hạn theo thời gian cho lớp chặn gửi (mảnh `days: 3650`, `purger: row_delete` cùng một bộ
      xóa đăng ký theo tuổi) → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `configs/policies/retention.d/platform.audit_events.yaml:3-5`, `.claude/plans/ops-hardening.md:22`; spec: R5.3 (mảnh để
  dành chỗ cho căn cứ pháp lý; dòng còn dẫn Nghị định 13/2023).
- `apps/worker/src/dw_worker/main.py:341`, `apps/worker/tests/unit/test_worker.py:226`; spec: R5.1, R5.2 (sổ bộ xóa của
  lane `retention` và test giữ mảnh với bộ xóa).
- `configs/policies/retention.d/platform.consent_records.yaml`, `platform.marketing_send_log.yaml`; spec: R5.1, R5.11
  (hai mảnh ticket 08 thêm với `enforced: false`).
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
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (người dựng và ranh giới, vì ticket thêm
  migration). CRITICAL 1: bộ xóa Bản ghi đồng ý xóa bằng chứng một người đã đồng ý mà không ghi audit (`CLAUDE.md` mục
  'Agent and tool rules': lane tự làm audit như chính nó; một dòng đọc lại được như việc một người đã làm là bản ghi,
  không phải dọn dẹp); sửa: `consent.expired` mỗi công ty, ở workspace cũ nhất vì bảng toàn tenant không có workspace
  (bước 1; spec R5.11, CP30). Nếu sai thì: `owning_workspace_id` trên Bản ghi đồng ý, ghi từ phạm vi của
  `ConsentLedger.record`, và một sự kiện mỗi workspace sở hữu.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 1: "theo quan hệ cộng 5 năm" không nói mốc đặt trên cột nào và có
  giữ đồng ý đang hiệu lực không (ADR-0124 (Accepted): "the row in force may be old"); sửa: hết quan hệ của một bộ là
  khi dòng mới nhất là `withdrawn`, mốc so với `withdrawn_at` của dòng đó, bộ còn `granted` không bao giờ hết hạn theo
  thời gian (bước 1; spec R5.11). Nếu sai thì: luật sư định nghĩa "hết quan hệ" khác (ví dụ lần gửi cuối), và hàm đổi
  điều kiện, mảnh giữ nguyên.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 2: hai mảnh của ticket 08 để `enforced: false`, nên bộ xóa đồng ý
  đăng ký mà không chạy và nhật ký gửi không bao giờ bị drop; sửa: ticket này bật cả hai. Nhật ký gửi: DROP PARTITION
  không lùi được, usage-and-limits/02 để quyết định cho lát này; bật ở đây vì ở W1 chỉ có dữ liệu giả lập (YC89) và một
  kho dữ liệu cá nhân không có bộ xóa là `failure-modes.md` #6; số 13 tháng do luật sư xác nhận trước dữ liệu thật. Nếu
  sai thì: đặt lại `enforced: false` (dừng các lần drop sau; tháng giả lập đã drop không cần lấy lại).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 3: EXECUTE của `dw_app` cho phép API gọi hai hàm xóa mà không
  audit; sửa: test quét nguồn chỉ cho bộ xóa của lane `retention` gọi chúng (bước 3), như luật một bên đặt
  `app.workspace_scope` của `CLAUDE.md`. Nếu sai thì: hai hàm tự ghi sự kiện audit trong thân, actor là hằng của
  `system_actor("retention")` có test so với Python.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 4: test tập bộ xóa không nói lấy danh sách kho ở đâu (một danh sách
  chép tay không đỏ khi có kho mới) và có nhận `purger: none` không; đã có câu trả lời một nửa:
  `test_every_purged_fragment_has_its_purger` đã đọc tập mảnh; sửa: thêm danh sách miễn có lý do cho `purger: none` và
  bốn kho của lát phải `enforced: true` (bước 3). Nếu sai thì: một cột "dữ liệu cá nhân" trong định dạng mảnh của
  telemetry-and-audit.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 5: R5.7 đọc được như giữ cả hội thoại còn hoạt động; ticket xóa từng
  tin quá hạn; sửa: spec R5.7 nói rõ tin quá hạn vẫn bị xóa trong hội thoại còn tin trong hạn, tiêu chí R5.7 thứ hai.
  Nếu sai thì: hạn tính từ hoạt động cuối của hội thoại và `studio.conversations` thêm cột hoạt động cuối.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (không CRITICAL mới, 4 HIGH, đã sửa): dòng mới
  nhất của một bộ theo đúng thứ tự của sàn, có test hai bên cùng chọn; hàm tự tìm workspace cũ nhất (nó thấy qua RLS);
  test âm hai công ty cho bộ xóa Bản ghi đồng ý (gom theo `tenant_id`); bộ xóa hội thoại bỏ qua hội thoại có lượt đang
  chạy, công ty `offboarding` và dòng còn bị FK khác dẫn tới. Thêm: hạn đồng ý không ngắn hơn hai kho dẫn tới nó; hàm
  đồng ý trong test quét nguồn. Nếu sai thì: từng mục quay về bản trước trong lịch sử git.
- 2026-11-04 (agent): neo chết `configs/policies/retention@1.7.0.yaml:118-120` thay bằng mảnh `platform.audit_events` và
  `ops-hardening.md:22`; bộ nạp đã từ chối hạn không dương và `indefinite` đi với `purger` khác `none`
  (`retention_policy.py:141-168`), nên hạn 0 hay âm không tới hàm xóa.
- 2026-11-04 (agent): MEDIUM, để người dựng: (a) một lượt xóa mọi công ty trong một giao dịch: một công ty ghi audit hỏng
  thì cả lượt lùi và chạy lại lần sau; (b) một tin gửi vào hội thoại đúng lúc hội thoại bị xóa gặp lỗi FK; đề xuất hàm
  khóa dòng hội thoại `FOR UPDATE SKIP LOCKED` trước khi xóa; (c) hai worker chạy lane `retention` cùng lúc: đề xuất
  khóa tư vấn của lane; (d) lần chạy đầu xóa mọi dòng quá hạn trong một câu lệnh; chia lô nếu đo thấy chậm.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
