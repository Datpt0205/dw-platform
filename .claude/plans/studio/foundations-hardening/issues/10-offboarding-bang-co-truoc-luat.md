# 10 — Bảng có trước luật của test phủ offboarding: xuất, xóa hay loại trừ đã kiểm

Status: resolved
Blocked by: 02, 08, 09
Area: studio
Yêu cầu: R11.16, R11.21, FH43

## Mục tiêu

Test phủ offboarding hôm nay bỏ qua 25 bảng `platform` có trước luật (`_PLATFORM_PREDATING`), nên một bảng trong đó mà
lane không xóa không làm test nào đỏ (failure-modes #0). Ticket này cho mỗi bảng đó một cách mất dòng mà test phủ kiểm
theo catalog, sửa bảng nào thật sự bị bỏ lại, rồi gỡ danh sách (R11.16).

## Việc cần làm

1. Đo ở `902ac246a9dc` ngày 5/11/2026 (test phủ với danh sách rỗng, mọi schema), 9 bảng được nêu tên: không xóa
   `platform.approval_decision_codes` (`CASCADE` qua `platform.approval_view_receipts`, hai bậc từ
   `platform.approval_requests`), `platform.approval_view_receipts` (`CASCADE` từ `platform.approval_requests`),
   `platform.audit_events` (giữ theo fragment retention), `platform.channel_deliveries` và `platform.notifications`
   (`CASCADE` từ `platform.workspaces`), `platform.support_grants` (`CASCADE` từ `platform.workspaces`),
   `platform.sod_waivers` (chỉ `CASCADE` từ `platform.tenants`, bảng lane không xóa); không xuất và không xóa
   `platform.channel_preferences` (policy theo `app.principal_id`, không có policy `tenant_isolation_*`; `CASCADE` từ
   `platform.memberships`) và `platform.tenant_offboarding_requests` (`_NEVER_PURGE`). Đo lại trên head lúc dựng: một
   bảng ngoài danh sách này mà một khóa ngoại `CASCADE` của `pg_constraint` nối tới bảng lane xóa nhận một dòng
   `cascade_from` như bước 2 và ghi vào Comments; bảng nào không vừa cách đó thì ticket về `needs-info`, không tự
   thêm `kept` hay một bước xóa.
2. Mỗi bảng có `CASCADE` một bậc từ bảng lane xóa: một dòng `OffboardingExclusion(cascade_from=...)` trong
   `STUDIO_EXCLUSIONS` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:226`).
   `platform.approval_decision_codes` nêu bảng cha trực tiếp, `cascade_from="platform.approval_view_receipts"`; kiểm R4.4
   của test phủ nhận một `cascade_from` khi bảng đó bị lane xóa hay chính nó có dòng `cascade_from` được nhận, mỗi mắt
   là một khóa ngoại `ON DELETE CASCADE` của `pg_constraint`, và `deleted_at` của test đi theo cùng chuỗi đó.
3. `platform.audit_events`: dòng `kept="platform.audit_events"` với term của
   `configs/policies/retention.d/platform.audit_events.yaml` (đang thi hành).
4. `platform.sod_waivers`: migration mới (`alembic revision -m "..."`, id ngẫu nhiên, `down_revision` là head lúc
   commit) tạo `platform.purge_tenant_sod_waivers(p_tenant uuid) RETURNS integer`, SECURITY DEFINER, `SET search_path`,
   cùng hình `platform.purge_tenant_service_users`
   (`db/migrations/versions/557e6907195e_service_principals_run_as.py:550-574`): từ chối với SQLSTATE 23514 khi
   `p_tenant IS DISTINCT FROM` `app.tenant_id` của giao dịch (nên cả khi setting chưa đặt hay rỗng) hay tenant không ở
   `offboarding` (R11.21), rồi xóa dòng của `p_tenant`; `REVOKE EXECUTE ... FROM PUBLIC` rồi EXECUTE chỉ cho `dw_app`,
   khẳng định trong `test_privileges.py`; `dw_app` vẫn không có DELETE trên bảng. Một `OffboardingPurgeStep` khai
   `platform.sod_waivers`, đăng ký trong `OffboardingPurgeSteps.platform()` (`offboarding.py:336-356`) như bước của
   service user. Dòng của tenant B ở bảng này vào test FH35. Bước này đảo câu "offboarding keeps them with the audit
   log" của `db/migrations/versions/6b26771e549d_separation_of_duties_waivers_per_tenant.py:19-21`; docstring của
   migration mới nói vậy và vì sao, migration cũ không sửa (Quyết định 5/11/2026, gate ticket 09 và 10, mục 5).
5. `platform.channel_preferences`: không vào gói xuất (Quyết định 5/11/2026, gate ticket 09 và 10, mục 8): một dòng
   `EXPORT_EXCLUSIONS` nêu lý do và một dòng `cascade_from="platform.memberships"`.
6. `platform.tenant_offboarding_requests`: một dòng `EXPORT_EXCLUSIONS` nêu lý do của `_NEVER_PURGE`; phía xóa, test phủ
   coi bảng của `_NEVER_PURGE` là đã xử lý, và một test khẳng định `_NEVER_PURGE` chỉ có bảng này (mục 6 của cùng
   Quyết định).
7. Gỡ `_PLATFORM_PREDATING`, tham số `predating` và kiểm R4.6 của nó khỏi
   `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py`.

## Tiêu chí chấp nhận

- [x] R11.16 (FH43): không còn `_PLATFORM_PREDATING`, `test_offboarding_covers_every_table_it_has_to` vẫn `[]` trên
      checkout đã migrate; bỏ một dòng loại trừ vừa thêm → test nêu tên bảng đó; sai nếu test xanh khi thiếu dòng.
- [x] R11.16 (FH43): một chuỗi thử hai bậc mà mắt giữa là `ON DELETE SET NULL` thay vì `CASCADE` → test nêu tên bảng
      cuối; sai nếu test xanh.
- [x] R11.16 (FH43): thêm một bảng thứ hai vào `_NEVER_PURGE` → test đỏ; sai nếu xanh.
- [x] R11.16 (FH43): purge tenant A khi A và B đều có dòng `platform.sod_waivers` → của A mất, của B còn; sai nếu dòng
      của A còn hay của B mất.
- [x] R11.21 (FH43): bằng `dw_app`, gọi `platform.purge_tenant_sod_waivers` cho tenant `active` với `app.tenant_id` của
      chính nó, cho tenant `offboarding` khác `app.tenant_id`, và cho tenant `offboarding` khi `app.tenant_id` chưa đặt →
      23514, 0 dòng bị xóa; `dw_agent_ro` gọi hàm → `permission denied`; gỡ từng phép kiểm → test của nó đỏ.
- [x] Xong: `uv run pytest -m integration packages/python/dw_platform/tests/integration/test_offboarding.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_rls_coverage.py`
      xanh.

## Nguồn

- `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py:51-80`
- `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py:163-166`
- `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py:172-213`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:193-218`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:412-428`
- `db/migrations/versions/6b26771e549d_separation_of_duties_waivers_per_tenant.py:127-140`
- `db/migrations/versions/9f2becb1bf80_platform_channel_inbound_messages_and_.py:28-41`
- spec: R11.16, R11.21, FH43; Quyết định 5/11/2026.

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): tách từ ticket 08 sau phép đo ở bước 1 (Quyết định 5/11/2026 của spec);
  `platform.sod_waivers` cần migration. Chưa gate.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (người dựng và đường biên, rồi lượt xác
  nhận). Đã sửa: R11.21, hàm xóa waiver từ chối tenant khác `app.tenant_id`, setting chưa đặt hay tenant không ở
  `offboarding`, EXECUTE thu khỏi PUBLIC, có test âm (CRITICAL: phép kiểm trên chủ đề không mặc định không có test âm);
  xóa waiver đảo một quyết định đã ghi ở migration `6b26771e549d` và ghi lý do vào Quyết định (HIGH);
  `platform.tenant_offboarding_requests` qua `_NEVER_PURGE`, vì `kept` cần thời hạn mà bảng không có (HIGH); chuỗi
  `CASCADE` hai bậc kiểm từng mắt (HIGH); bảng ngoài danh sách đo (HIGH); `channel_preferences` không vào gói (Quyết
  định 5/11/2026 của spec, mục 8). Mức của `platform.sod_waivers` còn sau offboarding: HIGH, không CRITICAL. Đó là dữ
  liệu cá nhân (người cấp, xác nhận, thu hồi và lý do) của một công ty đã rời, giữ mãi không thời hạn (failure-modes
  #6), nhưng không lộ sang tenant khác, vì RLS theo tenant vẫn đứng và không ai của công ty đó còn đăng nhập. Ticket này
  sửa nó. MEDIUM, không sửa: (1) ticket này và các ticket `ready-for-agent` thêm dòng loại trừ vào
  `test_offboarding_coverage.py` hay `offboarding.py` (workflow-nodes/04, 06, 07; connections-and-vault/05;
  runtime-hardening/04) không chạy song song ở hai lane. (2) Gate không chạy lại phép đo 9 bảng vì cơ sở dữ liệu thử
  đang có hai lane dùng; khóa ngoại của `platform.sod_waivers` và `platform.channel_preferences` đã đọc ở migration.
  (3) Tenant giữ `offboarding` suốt lúc yêu cầu ở `purging`, vì hoàn tất cần `completed`
  (`packages/python/dw_platform/src/dw_platform/application/provisioning.py:396-411`), nên phép kiểm trạng thái của hàm
  không chặn lượt làm tiếp (R11.10).
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): đo lại bước 1 trên head có migration `4fb92ed062dc` của ticket 09
  (test phủ với danh sách rỗng, mọi schema): đúng 9 bảng của danh sách đo, không bảng nào ngoài nó; mọi mắt
  `cascade_from` đọc ở `pg_constraint` là `ON DELETE CASCADE`. Dựng xong: migration `9cc87820a05f` tạo
  `platform.purge_tenant_sod_waivers` (lỗi mang `ck_sod_waivers_purge`), bước `platform.purge_tenant_sod_waivers`
  đăng ký trong `OffboardingPurgeSteps.platform()`; bảy dòng `STUDIO_EXCLUSIONS` (sáu `cascade_from`, một `kept`), hai
  dòng `EXPORT_EXCLUSIONS`. Test phủ nhận tham số `never_purge` (mặc định `_NEVER_PURGE`) để ca "thêm bảng thứ hai"
  chạy được mà không sửa mã của lane, và nêu một dòng R11.16 khi tập đó khác bảng yêu cầu. Gỡ `_PLATFORM_PREDATING`
  kéo theo gỡ kiểm R4.6 (OID sau `platform.time_partitioned_tables`) và ca R4.5 "predating names no table"; ca
  `platform-predating` của FH41 đổi tên thành `platform`. Dòng FH35 của bảng nằm ở test riêng
  `test_offboarding_deletes_the_companys_waivers_and_no_one_elses` (`test_offboarding.py`), không ở
  `test_steps_delete_only_the_offboarded_tenant`, vì test đó dựng sổ chỉ có bước thử. Nếu sai thì: test FH35 dùng
  `OffboardingPurgeSteps.platform()` cộng bước thử và đếm thêm `platform.sod_waivers`. Hai nơi khác gọi
  `offboarding_violations` với danh sách cũ (`test_append_only_purge_db.py` của `dw_usage`,
  `db/bench/offboarding/bench_offboarding.py`) bỏ tham số đó trong cùng commit.
- 2026-11-05 (agent): FH43 có bốn test ở `test_offboarding.py` (purge A còn B, ba lời gọi bị từ chối 23514 của
  `dw_app`, một lời gọi đúng làm đối chứng, `dw_agent_ro` bị `permission denied`), năm test mới ở
  `test_offboarding_coverage.py` và một ở `test_privileges.py`; `mutations/10.yaml` có bảy đột biến, bốn đã bẻ bằng
  tay một lần, đều đỏ. `scripts/mutate.py`, độ trễ của lượt purge (thêm một lời gọi hàm) và `/code-review` chạy lúc
  đóng hàng.
