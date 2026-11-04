# 09 — Lưu giữ hai bảng hội thoại

Status: needs-triage
Blocked by: 06, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.7, R5.8, R5.9, R5.10, CP16, CP20, CP22, CP23

## Mục tiêu

Hai bảng hội thoại mà agent-builder/04 tạo có một thời hạn 90 ngày và một bộ xóa đã đăng ký: tin quá hạn bị xóa qua
một hàm hẹp không đối số, đọc hạn ở `platform.retention_terms` thay cho một hằng trong thân hàm (V4.21), mà lane lưu
giữ gọi và audit như chính lane (spec R5.1, R5.2, R5.7-R5.10; ADR-0106 (Accepted), ADR-0122 (Accepted) quyết 7). Tách
từ ticket 06 ngày 4/11/2026, vì agent-builder/04 CẦN XEM theo D15/D17: bản viết lại của nó (kênh chat vào Digital
Worker) quyết hai bảng còn hay đổi hình, và ticket này viết lại theo bản đó trước khi gate.

## Việc cần làm

1. Mảnh retention hội thoại theo định dạng của telemetry-and-audit/01 (H-1; DO-52), số ghi UNVERIFIED tới khi luật sư
   xác nhận: mảnh `configs/policies/retention.d/studio.conversations.yaml` với `days: 90` (DO-52, Đạt 24/10/2026),
   `purger: row_delete`, `enforced: true`, cùng bộ xóa của hai bảng hội thoại là hàm của bước 2, và đổi mảnh
   `studio.conversation_messages` 90 ngày mà agent-builder/04 thêm với `enforced: false` thành `enforced: true` trong
   cùng thay đổi, vì bộ xóa của nó ra đời ở đây; đăng ký ở `build_retention_purgers`.
2. Migration (id hex ngẫu nhiên): hàm `studio.purge_expired_conversations()` SECURITY DEFINER, không đối số
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

- [ ] R5.1 (CP16): mảnh `studio.conversations` và `studio.conversation_messages` có trong tập mảnh retention đang ghim,
      `enforced: true`, với bộ xóa đã đăng ký; gỡ mảnh `studio.conversations` → test phủ mảnh của telemetry-and-audit/01
      đỏ, nêu tên bảng.
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
      đỏ.
- [ ] R5.10 (CP23): xóa dòng `studio.conversations` khỏi bảng thử → `studio.purge_expired_conversations()` báo lỗi,
      không tin hay hội thoại nào bị xóa; hai dòng hội thoại 90 và 120 → báo lỗi, không dòng nào bị xóa; hàm dùng hạn
      mặc định khi thiếu dòng → test đỏ.
- [ ] R5.2 (CP16): mảnh của một trong hai bảng hội thoại `enforced: false` → test tập bộ xóa của ticket 06 đỏ; một
      mô-đun của API gọi `studio.purge_expired_conversations()` → test quét nguồn của ticket 06 đỏ.
- [ ] R5.7 (CP20): hội thoại có tin 91 ngày và tin 89 ngày → tin 91 ngày bị xóa, dòng hội thoại và tin 89 ngày còn.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:168-190`; spec: R5.7 (hàm xóa không nhận đối
  số, tiền lệ `platform.prune_notifications()`).
- `packages/python/dw_platform/src/dw_platform/domain/audit.py:72`; spec: R5.8 (`lane_audit_event` đòi `workspace_id`).
- telemetry-and-audit:R5.9, telemetry-and-audit:R5.10; spec: R5.9, R5.10 (bảng thời hạn và hàm đọc hạn).
- ADR-0011 (Accepted); ADR-0122 (Accepted) quyết 7.

## Comments

- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách từ ticket 06 trong `checking-plan-consistency` của vùng studio
  (I:agent-builder/04~compliance-pdpl/06, HIGH): ticket 06 `ready-for-agent` chờ agent-builder/04 `needs-triage`, ticket
  CẦN XEM vì dựng trên trợ lý chat riêng mà D15 bỏ. Nội dung là bước 1 (vế hội thoại) và bước 4 của ticket 06 cùng các
  tiêu chí hội thoại của nó, chép nguyên; gate của ticket 06 ngày 4/11/2026 đã xét chúng, nhưng ticket này gate lại sau
  bản viết lại của agent-builder/04. Nếu sai thì: gộp lại vào ticket 06 khi bản viết lại giữ hai bảng, và ticket 06 lại
  chờ agent-builder/04.
