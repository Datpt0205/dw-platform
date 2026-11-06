# 12 — Lần đổi người của membership qua các guard mà lần gán và lần gỡ phải qua

Status: ready-for-agent
Blocked by: 11
Area: studio
Yêu cầu: R3.11, R3.12, R6.7, RB20, RB39, RB40, RB50

## Mục tiêu

R3.11: không lệnh ghi nào, "kể cả `dw_provisioner` và `dw_migrator`", làm người vận hành nền tảng hay nhân viên
`support_staff` giữ `tenant_owner`, `studio.publish.approve` hay `platform.roles.write` trong một tenant. Hôm nay điều đó
chỉ đúng cho lần gán, lần thêm khóa vào vai trò và lần ghi hai bảng danh sách: `dw_migrator` đổi
`platform.memberships.user_id` (lối duy nhất RB50 để mở) mang mọi lần gán của membership sang người khác mà không guard
nào trên `platform.role_assignments` xét. Cùng lối đó đưa vai trò trọng yếu tới tài khoản dịch vụ, không sự kiện xét lại
(org-and-principals:R6.4, org-and-principals:R6.6, ADR-0103 (Accepted) quyết 2), làm tenant `active` hay `locked`
mất chủ sở hữu `active` cuối (R6.7), và hạ số người giữ một khóa chủ xuống dưới hai không cảnh báo (R3.12). Ticket 11 cho
lần đổi người qua tách nhiệm; ticket này cho nó qua bốn luật còn lại áp cho mọi người ghi: lần đổi người là một lần gỡ
khỏi người cũ cộng một lần gán cho người mới, như "Nếu sai thì (1)" của gate ticket 03 đã đặt tên. Hai guard của lần gán
cũng đọc người của membership không khóa, nên một lần gán lên M cạnh lần đổi người của M được xét theo người cũ; và
guard R3.11 không khóa gì khi thêm khóa chủ vào vai trò: ticket này khóa cả hai chỗ.

## Việc cần làm

Đọc ở `7a0c110c` (5/11/2026):

- `platform.guard_membership_identity` từ chối mọi người ghi trừ `dw_migrator`
  (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:997-1015`, trigger BEFORE
  `UPDATE OF tenant_id, workspace_id, user_id` ở `d2b57239ef50_role_administration_and_anti_escalation.py:1144-1146`).
  Khóa ngoại của lần gán trên `(tenant_id, workspace_id, membership_id)` không `ON UPDATE CASCADE`
  (`db/migrations/versions/b5677d345bc1_tenant_roles.py:159-161`), nên chỉ đổi `user_id` mang lần gán đi. Người mới phải
  là thành viên công ty của tenant (`fk_memberships_tenant_members`,
  `db/migrations/versions/349080a62e41_tenant_members.py:151-153`) và chưa có membership ở workspace đó
  (`uq_memberships_scope_user`, `db/migrations/sql/0001_platform_baseline.sql:608`). Không code nào của repo đổi
  `memberships.user_id`; chỉ script `dw_migrator`.
- R3.11: `platform.guard_operator_tenant_grants()` (`db/migrations/versions/b5677d345bc1_tenant_roles.py:876-937`, một
  phần tử của `_SETUP` ở `b5677d345bc1_tenant_roles.py:797`), BEFORE trên `role_assignments`, `tenant_role_permissions`
  và INSERT `platform_operators`, `support_staff` (`b5677d345bc1_tenant_roles.py:1176-1186`); nhánh `role_assignments`
  lấy `pg_advisory_xact_lock(hashtext('operator_grants:' || v_user::text))` rồi đọc hai bảng danh sách và vai trò; mọi
  người ghi; 23514 `ck_role_assignments_operator_not_owner`. Khóa của hai khóa: `platform.owner_permission_keys()`
  (`b5677d345bc1_tenant_roles.py:213-216`). Nhánh `role_assignments` đọc `memberships.user_id` không khóa
  (`b5677d345bc1_tenant_roles.py:891`); nhánh `tenant_role_permissions` không lấy khóa nào
  (`b5677d345bc1_tenant_roles.py:904-914`), nên một lần gán vai trò R cho người vận hành và một lần thêm khóa chủ vào R
  ở hai giao dịch cùng qua được (RB39 không có ca đồng thời nào ngoài hai bảng danh sách).
- Tài khoản dịch vụ: `platform.guard_service_principal_grants()`, thân mới nhất là `_GUARD_GRANTS` của
  `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:547-588` (dựng từ
  `db/migrations/versions/557e6907195e_service_principals_run_as.py:314-361`), mỗi nhánh khóa dòng vai trò
  `FOR NO KEY UPDATE` trước khi đọc, rồi `platform.role_is_critical` (một chủ của "vai trò trọng yếu",
  `ef68083f2905_object_and_field_privileges_in_roles.py:343`); 23514 `ck_role_assignments_service_not_critical`.
  Nhánh `role_assignments` cũng đọc người của membership không khóa (`557e6907195e_service_principals_run_as.py:324-328`).
  Ở READ COMMITTED một lần gán lên M chạy khi lần đổi người của M chưa commit thấy người cũ, qua cả hai guard, rồi chỉ
  chờ ở khóa ngoại (`FOR KEY SHARE` trên M) lúc guard đã qua.
  Sự kiện R6.6 của org-and-principals: `platform.service_principal_grants_changed()`
  (`557e6907195e_service_principals_run_as.py:366-433`), một dòng outbox `platform.service_principal.grants_changed`
  mỗi tài khoản dịch vụ có quyền được gán tăng. Trigger của cả hai đặt tên để bắn trước `trg_z_bump_access_version`:
  dòng vai trò trước dòng version (`557e6907195e_service_principals_run_as.py:435-446`). Một người dùng `service` chỉ là
  thành viên công ty của tenant của nó (`557e6907195e_service_principals_run_as.py:254-271`).
- R6.7: `platform.refuse_losing_the_last_owner()`
  (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:862-932`), AFTER trên
  `role_assignments` và `UPDATE OF status` trên `tenant_members` (`d2b57239ef50_role_administration_and_anti_escalation.py:1126-1131`),
  không miễn người ghi nào; khóa dòng `platform.tenants` `FOR UPDATE` rồi đếm `platform.active_tenant_owners`.
- R3.12: bước 1 của ticket 08 thay ba trigger theo câu lệnh bằng một trigger ràng buộc `DEFERRABLE INITIALLY DEFERRED`
  mỗi bảng của `_COVERED_TABLES` (`role_assignments`, `tenant_role_permissions`, `tenant_roles`, `tenant_members`;
  `db/migrations/versions/b5677d345bc1_tenant_roles.py:1031`) gọi `platform.owner_coverage_after_write()`, hàm đọc
  `OLD.tenant_id`, `NEW.tenant_id` và không đọc bảng nào theo `TG_TABLE_NAME`. `memberships` không trong tập đó.
- Ticket 11 thêm trên `platform.memberships` trigger AFTER `UPDATE OF user_id` `trg_memberships_separation_of_duties`,
  câu đầu khóa dòng `platform.tenant_access_versions` của công ty `FOR NO KEY UPDATE`. Trigger AFTER theo dòng bắn theo
  thứ tự tên, BEFORE trước AFTER.
- Mẫu test: R3.11 ở `packages/python/dw_platform/tests/integration/test_tenant_roles.py:866-921` (dưới `dw_migrator` và
  `dw_provisioner`, hai bảng danh sách); RB50 ở
  `packages/python/dw_platform/tests/integration/test_role_administration_db.py:1636-1687`; cuộc đua hai kết nối thật
  `_race`, `_blocked`, `_until` và ca OP9 ở `packages/python/dw_platform/tests/integration/test_service_principals_db.py:386-470`;
  hàm gieo `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`.

Việc:

1. **Migration**: một revision (id hex của `alembic revision`, `down_revision` là head lúc commit, sau revision của
   ticket 11). Mỗi hàm dựng từ thân đã có, nạp bằng `_earlier()` và sửa bằng `_patched()` (neo khớp đúng một lần,
   `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100`), `CREATE OR REPLACE`, không chép
   tay; thân ở `_SETUP` lấy theo phần tử chứa `guard_operator_tenant_grants()`, không theo chỉ số.
    - `platform.guard_operator_tenant_grants()`, bốn chỗ:
        - nhánh `role_assignments`: câu đọc người của membership thành `SELECT user_id INTO v_user FROM
platform.memberships WHERE id = NEW.membership_id FOR KEY SHARE` (khóa mà khóa ngoại của lần gán lấy muộn hơn
          trong cùng lệnh; nó xung đột với khóa của một lần đổi `user_id` chưa commit, nên lần gán chờ rồi đọc người
          mới); sau khóa tư vấn, khi `v_user` có dòng trong một trong hai bảng danh sách, khóa dòng vai trò
          `NEW.role_id` `FOR NO KEY UPDATE` trước khi đọc quyền của nó;
        - nhánh `tenant_role_permissions`: khi `NEW.permission_key = ANY (platform.owner_permission_keys())`, khóa dòng
          vai trò `NEW.role_id` `FOR NO KEY UPDATE` trước khi đọc người giữ; khóa khác thì không khóa gì;
        - nhánh mới `ELSIF TG_TABLE_NAME = 'memberships'` đặt trước nhánh `ELSE` (nhánh hai bảng danh sách):
          `v_user := NEW.user_id`, cùng `pg_advisory_xact_lock` với khóa `'operator_grants:' || v_user::text`; khi
          `v_user` có dòng trong một trong hai bảng danh sách, khóa `FOR NO KEY UPDATE` các dòng `platform.tenant_roles`
          của mọi lần gán của membership, `ORDER BY id`, rồi từ chối khi một lần gán của chính membership này
          (`a.tenant_id = NEW.tenant_id AND a.membership_id = NEW.id`) mang vai trò `tenant_owner` hay vai trò có khóa
          trong `platform.owner_permission_keys()`, cùng câu xét vai trò của nhánh `role_assignments` (không lọc
          `deleted_at`, `expires_at`, như nhánh đó). Chỉ lần gán của membership này: không đọc membership khác của
          người cũ hay người mới, không tenant khác;
        - nhánh `ELSE` (INSERT `platform_operators`, `support_staff`): sau khóa tư vấn, khóa `FOR NO KEY UPDATE` các
          dòng `platform.tenant_roles` của mọi lần gán của `v_user` ở mọi tenant, `ORDER BY id`, rồi mới đọc, để lần thêm
          người vào danh sách và lần thêm khóa chủ vào một vai trò người đó giữ không cùng qua (nhánh
          `tenant_role_permissions` giữ dòng vai trò, không lấy khóa tư vấn).
    - `platform.guard_service_principal_grants()`, hai chỗ:
        - nhánh `role_assignments`: câu đầu `PERFORM 1 FROM platform.memberships WHERE id = NEW.membership_id FOR KEY
SHARE;` trước câu đọc người, cùng lý do;
        - nhánh mới `ELSIF TG_TABLE_NAME = 'memberships'` đặt trước nhánh `field_permissions` (nhánh khôi phục cuối đọc
          `OLD.deleted_at`, cột `memberships` không có): khi `NEW.user_id` là người dùng `kind = 'service'`, khóa
          `FOR NO KEY UPDATE` các dòng `platform.tenant_roles` của mọi lần gán của membership, `ORDER BY id`, như nhánh
          `field_defs`, rồi từ chối khi một vai trò đó `platform.role_is_critical`. Người mới không phải tài khoản dịch
          vụ thì không khóa gì.
    - `platform.service_principal_grants_changed()`: nhánh mới `TG_TABLE_NAME = 'memberships'` đặt trước nhánh
      `role_assignments`: `v_principals` là `NEW.user_id` khi người đó `kind = 'service'` và membership có ít nhất một
      lần gán, kể cả lần gán đã hết hạn hay của vai trò đã xóa mềm (như nhánh `role_assignments`, không lọc: báo thừa
      chỉ đưa binding về xét lại, báo thiếu để quyền tăng không ai xét); rỗng thì `RETURN NULL`; phần INSERT outbox chung
      giữ nguyên.
    - `platform.refuse_losing_the_last_owner()`: nhánh mới `ELSIF TG_TABLE_NAME = 'memberships'` đặt trước nhánh `ELSE`
      (`tenant_members`): membership không có lần gán `tenant_owner` thì `RETURN NULL`; có thì `v_tenant := NEW.tenant_id`,
      `v_user := OLD.user_id`, rồi phần chung (người cũ `active`, tenant `active` hay `locked`, khóa dòng tenant, đếm).
    - R3.12: một trigger ràng buộc trên `platform.memberships` cùng dạng ticket 08 để lại cho bốn bảng của
      `_COVERED_TABLES` (tìm theo tên hàm `platform.owner_coverage_after_write()`, không chép), chỉ
      `AFTER UPDATE OF user_id`, `DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.user_id IS DISTINCT FROM
OLD.user_id)`, tên `trg_memberships_owner_coverage`. Hàm không đổi: nó đọc `OLD.tenant_id`, `NEW.tenant_id`, và
      `memberships` có trong `_BUMPED_TABLES`, nên dấu của tenant cũ đi khi version đổi. `_COVERED_TABLES` của
      `b5677d345bc1` không sửa (revision cũ bất biến).
    - Bốn trigger theo dòng, mỗi cái `FOR EACH ROW WHEN (NEW.user_id IS DISTINCT FROM OLD.user_id)` trên
      `platform.memberships`, cạnh trigger ràng buộc trên:
      `guard_service_principal_grants BEFORE UPDATE OF user_id`, `trg_memberships_operator_not_owner BEFORE UPDATE OF
user_id`, `ck_role_assignments_last_owner AFTER UPDATE OF user_id`, `service_principal_grants_changed AFTER UPDATE OF
user_id`. Một thứ tự khóa cho mọi đường: dòng membership, dòng vai trò, khóa tư vấn, dòng tenant, dòng version. Lần
      đổi người khóa dòng M bằng chính lệnh UPDATE, rồi BEFORE theo tên: `guard_membership_identity`,
      `guard_service_principal_grants` (dòng vai trò khi người mới là tài khoản dịch vụ),
      `trg_memberships_operator_not_owner` (khóa tư vấn, rồi dòng vai trò khi người mới có trong danh sách); AFTER:
      `ck_role_assignments_last_owner` (dòng tenant), `service_principal_grants_changed`,
      `trg_memberships_separation_of_duties` của ticket 11 rồi `trg_z_bump_access_version` (dòng version). Lần gán: dòng
      M (`FOR KEY SHARE` ở guard đầu), dòng vai trò khi người là tài khoản dịch vụ, khóa tư vấn, dòng vai trò khi người
      có trong danh sách, rồi các khóa của ticket 11. Một người vừa là tài khoản dịch vụ vừa có trong danh sách lấy dòng
      vai trò trước khóa tư vấn ở guard đầu và sau ở guard sau: cùng dòng, cùng chế độ, đã giữ, nên không chờ. Dưới
      `dw_app` hay `dw_provisioner`, `guard_membership_identity` (tên xếp trước) vẫn từ chối trước với
      `ck_memberships_identity_fixed`, nên RB50 không đổi. Lần thêm người vào danh sách: khóa tư vấn rồi dòng vai trò,
      cùng thứ tự. Ngoài thứ tự đó, có chủ là ticket 08: trigger ràng buộc hoãn tới commit (cả
      `trg_memberships_owner_coverage`) gọi `check_owner_coverage`, mà lần chuyển xuống dưới hai người ghi
      `platform.tenants` (`d2b57239ef50_role_administration_and_anti_escalation.py:1066-1067`) sau khi giao dịch đã giữ
      dòng version; cạnh một lần ghi lấy dòng tenant rồi dòng version (`refuse_losing_the_last_owner`) nó có thể cho
      `40P01`, một bên bị hủy, không lọt. Ticket này không đổi thứ tự đó; K3, K4 không có ca đồng thời.
    - Không bảng, cột, quyền vai, hàm mới, route hay bước offboarding mới (offboarding chỉ DELETE membership, không đổi
      `user_id`), nên `test_rls_coverage.py`, `test_privileges.py` và `test_offboarding_coverage.py` không đổi và phải
      xanh. Không route nào đổi `user_id`, nên không ánh xạ lỗi API mới.
    - Downgrade dựng lại bốn thân trước (từ chính các module `_earlier`), DROP năm trigger mới.
2. **Test** (integration, tệp mới `packages/python/dw_platform/tests/integration/test_membership_change_of_person.py`;
   không sửa `test_tenant_roles.py`, `test_service_principals_db.py`, `test_role_administration_db.py` hay tệp test của
   ticket 11): mỗi ca trên tenant gieo mới dưới `dw_migrator`, mọi lần đổi `UPDATE platform.memberships SET user_id = :p
WHERE id = :m` dưới `dw_migrator`; mỗi lần từ chối khẳng định SQLSTATE 23514, tên ràng buộc, `user_id` của M không
   đổi và số dòng `role_assignments` của M không đổi. Ca đồng thời theo dạng `_race` của
   `test_service_principals_db.py:407-437` (bên thứ nhất giữ giao dịch mở, bên thứ hai chạy trong một task tới khi chờ
   khóa hay đã xong, bên thứ nhất commit; không ngủ cố định), hai thứ tự; mỗi ca đồng thời đếm SQLSTATE `40P01`, phải
   là 0. Ca R3.12 đếm dòng outbox sau commit, như test K4 của ticket 11.
3. `reviewing-feature-security` (ranh giới 1, 2, 5, 6), `mutations/12.yaml` một đột biến mỗi dòng ở cột "Đột biến"
   dưới đây, không chạy `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng tay. Độ trễ: năm trigger mới
   chỉ bắn khi `user_id` đổi, không route nào làm việc đó; hai câu khóa thêm vào nhánh `role_assignments` và nhánh khóa
   chủ chạy trên lần gán, nên `q2` của `make bench-rbac` (lần gán 1.000 người, "thêm 10 khóa") đo trước và sau ở lúc
   đóng hàng đợi (`.claude/rules/latency.md`, `.claude/rules/wave-close.md`).

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                                              | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Đột biến (`mutations/12.yaml`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | Đổi người không đưa quyền chủ tới người vận hành hay `support_staff`   | Tenant A; P là thành viên công ty, có dòng trong `platform_operators` (rồi, ca riêng, `support_staff`); M của Q mang `tenant_owner` → đổi M sang P: 23514 `ck_role_assignments_operator_not_owner`; cùng với M chỉ mang vai trò có `platform.roles.write`, rồi `studio.publish.approve`, ở mức `tenant` → từ chối. Đối chứng: M chỉ mang vai trò không có khóa chủ → nhận; hai tenant: Q giữ `tenant_owner` ở A qua M_A và một vai trò thường ở B qua M_B, đổi M_B sang P → nhận. Đồng thời, mỗi ca hai thứ tự, đúng bên thứ hai bị từ chối: (i) đổi M sang P cạnh INSERT `platform_operators` cho P; (ii) đổi M (vai trò thường) sang P cạnh gán `tenant_owner` lên M; (iii) đổi M (mang vai trò R không khóa chủ) sang P cạnh thêm `platform.roles.write` vào R; (iv) gán R cho người vận hành cạnh thêm `platform.roles.write` vào R; (v) INSERT `platform_operators` cho P cạnh thêm `platform.roles.write` vào vai trò R mà P đang giữ qua một membership khác | (a) bỏ trigger `trg_memberships_operator_not_owner`; (b) nhánh đọc lần gán của người mới (`m.user_id = NEW.user_id`, thân nhánh `ELSE`) thay vì của M; (c) bỏ vế `support_staff` của nhánh; (d) nhánh đọc lần gán của mọi membership của `OLD.user_id` (ca hai tenant đỏ); (e) bỏ `pg_advisory_xact_lock` của nhánh (ca (i) đỏ); (f) bỏ `FOR KEY SHARE` ở nhánh `role_assignments` (ca (ii) đỏ); (g) bỏ câu khóa dòng vai trò ở nhánh `tenant_role_permissions` (ca (iii), (iv) đỏ); (h) bỏ câu khóa dòng vai trò ở nhánh `ELSE` (ca (v) đỏ) |
| K2  | Đổi người không đưa vai trò trọng yếu tới tài khoản dịch vụ, và có báo | S là tài khoản dịch vụ của tenant A (có dòng `platform.service_principals`); M của Q ở workspace S chưa có membership, mang `tenant_owner` → đổi M sang S: 23514 `ck_role_assignments_service_not_critical`; cùng với M mang vai trò có một khóa `risk = 'critical'` → từ chối. Đối chứng: M chỉ mang vai trò không trọng yếu → nhận và đúng một dòng outbox `platform.service_principal.grants_changed` cho S; M không có lần gán nào → nhận, không dòng outbox. Đồng thời, mỗi ca hai thứ tự, đúng bên thứ hai bị từ chối: (i) đổi M (mang vai trò R không trọng yếu) sang S cạnh thêm khóa `critical` vào R; (ii) đổi M (vai trò không trọng yếu) sang S cạnh gán `tenant_owner` lên M                                                                                                                                                                                                                                                                           | (a) bỏ trigger `guard_service_principal_grants` trên `memberships`; (b) nhánh xét `OLD.user_id`; (c) nhánh dùng `r.key = 'tenant_owner'` thay cho `platform.role_is_critical` (ca khóa `critical` đỏ); (d) bỏ câu khóa dòng vai trò của nhánh (ca (i) đỏ); (e) bỏ trigger `service_principal_grants_changed` trên `memberships` (ca sự kiện đỏ); (f) bỏ `PERFORM ... FOR KEY SHARE` ở nhánh `role_assignments` (ca (ii) đỏ)                                                                                                                  |
| K3  | Đổi người không làm tenant mất chủ sở hữu `active` cuối                | Tenant `active`, Q là chủ sở hữu `active` duy nhất qua M; P là thành viên công ty `invited` → đổi M sang P: 23514 `ck_role_assignments_last_owner`; cùng ca ở tenant `locked` → từ chối. Đối chứng: P `active` → nhận (P giữ `tenant_owner`); M không mang `tenant_owner` → nhận                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | (a) bỏ trigger `ck_role_assignments_last_owner` trên `memberships`; (b) nhánh lấy `v_user := NEW.user_id` (ca `invited` đỏ)                                                                                                                                                                                                                                                                                                                                                                                                                  |
| K4  | Đổi người hạ số người giữ khóa chủ thì cảnh báo                        | Tenant `active`, đúng hai người `active` giữ `platform.roles.write` (Q qua M, và O); đổi M sang P `invited` dưới `dw_migrator`, commit → đúng một sự kiện `platform.tenant.owner_coverage_low` và `owner_coverage_low_since` khác NULL. Đối chứng: đổi M sang P `active` → không sự kiện, `owner_coverage_low_since` vẫn NULL                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | (a) bỏ trigger `trg_memberships_owner_coverage`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

## Tiêu chí chấp nhận

- [ ] R3.11 (RB39): K1, lần đổi người dưới `dw_migrator` đưa `tenant_owner`, `platform.roles.write` hay
      `studio.publish.approve` tới người có dòng trong `platform_operators` hay `support_staff` bị từ chối với 23514
      `ck_role_assignments_operator_not_owner`, M giữ `user_id` cũ và các lần gán của nó; ca vai trò thường và ca hai tenant
      được nhận; năm ca đồng thời từ chối đúng bên thứ hai ở cả hai thứ tự, không `40P01`; sai nếu lần đổi hay lần ghi
      nào đó được nhận, một ca đối chứng bị từ chối, hay một trong tám đột biến của K1 vẫn xanh. Ở commit gốc (sau ticket 11) các lần đổi đó được nhận, và ca đồng thời (ii)-(v) nhận cả hai bên.
- [ ] RB50: K2, lối `dw_migrator` mà RB50 để mở không đưa vai trò trọng yếu tới tài khoản dịch vụ
      (org-and-principals:R6.4): lần đổi M mang `tenant_owner` hay vai trò có khóa `critical` sang S bị từ chối với 23514
      `ck_role_assignments_service_not_critical`, M không đổi; lần đổi M chỉ mang vai trò không trọng yếu được nhận với
      đúng một dòng outbox `platform.service_principal.grants_changed` cho S (org-and-principals:R6.6), M không có lần gán
      thì không dòng nào; hai ca đồng thời từ chối đúng bên thứ hai ở cả hai thứ tự, không `40P01`; RB50 dưới `dw_app` và
      `dw_provisioner` vẫn `ck_memberships_identity_fixed` (`test_a_membership_never_changes_hands` xanh); sai nếu một lần đổi đưa vai trò
      trọng yếu tới S được nhận, số dòng outbox khác, hay một trong sáu đột biến của K2 vẫn xanh. Ở commit gốc lần đổi đó
      được nhận và không dòng outbox nào.
- [ ] R6.7 (RB20): K3, lần đổi người dưới `dw_migrator` làm tenant `active` hay `locked` không còn chủ sở hữu `active`
      bị từ chối với 23514 `ck_role_assignments_last_owner`, M giữ `user_id` cũ; ca P `active` và ca M không mang
      `tenant_owner` được nhận; sai nếu lần đổi đó được nhận, một ca đối chứng bị từ chối, hay một trong hai đột biến của K3
      vẫn xanh. Ở commit gốc lần đổi được nhận.
- [ ] R3.12 (RB40): K4, lần đổi người dưới `dw_migrator` hạ số người `active` giữ `platform.roles.write` của tenant
      `active` xuống dưới hai cho đúng một sự kiện `platform.tenant.owner_coverage_low` sau commit; ca P `active` không cho
      sự kiện nào; sai nếu không có hay có hai sự kiện, ca đối chứng cho sự kiện, hay đột biến của K4 vẫn xanh. Ở commit
      gốc (sau ticket 11) không sự kiện nào.
- [ ] Xong: `uv run python -m pytest packages/python/dw_platform/tests/integration/test_membership_change_of_person.py packages/python/dw_platform/tests/integration/test_role_write_races.py packages/python/dw_platform/tests/integration/test_tenant_roles.py packages/python/dw_platform/tests/integration/test_service_principals_db.py packages/python/dw_platform/tests/integration/test_role_trigger_cost_db.py packages/python/dw_platform/tests/integration/test_role_administration_db.py::test_a_membership_never_changes_hands packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py` xanh.

## Nguồn

- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:997-1015`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1144-1146` (danh tính membership); `db/migrations/versions/b5677d345bc1_tenant_roles.py:159-161` (khóa ngoại của lần gán); `db/migrations/versions/349080a62e41_tenant_members.py:151-153`; `db/migrations/sql/0001_platform_baseline.sql:608`.
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:876-937`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:1176-1186`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:213-216`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:891`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:904-914` (R3.11).
- `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:547-588`, `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:343`, `db/migrations/versions/557e6907195e_service_principals_run_as.py:254-271`, `db/migrations/versions/557e6907195e_service_principals_run_as.py:314-361`, `db/migrations/versions/557e6907195e_service_principals_run_as.py:324-328`, `db/migrations/versions/557e6907195e_service_principals_run_as.py:366-446` (tài khoản dịch vụ).
- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:862-932`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1126-1131` (R6.7); `db/migrations/versions/b5677d345bc1_tenant_roles.py:1031` (R3.12) và bước 1 của ticket 08.
- `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100` (`_earlier`, `_patched`).
- `packages/python/dw_platform/tests/integration/test_tenant_roles.py:866-921`, `packages/python/dw_platform/tests/integration/test_role_administration_db.py:1636-1687`, `packages/python/dw_platform/tests/integration/test_service_principals_db.py:386-470`, `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`.
- Spec: R3.11, R3.12, R6.7, RB20, RB39, RB40, RB50; org-and-principals:R6.4, org-and-principals:R6.6 (OP9); ADR-0104 (Accepted) mục 6, 10, Amendments 2026-11-04 (mục 10, danh tính membership), Amendments 2026-11-05; ADR-0103 (Accepted) quyết 2; MEDIUM (a) lượt đầu và (c) lượt xác nhận của gate ticket 11.

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cắt từ MEDIUM (a) lượt đầu và (c) lượt xác nhận của gate ticket 11:
  `dw_migrator` đổi `memberships.user_id` vẫn đưa vai trò trọng yếu tới người vận hành, `support_staff` hay tài khoản
  dịch vụ, trái R3.11 ("kể cả `dw_migrator`"). Đọc lại mọi luật trên `role_assignments` không miễn `dw_migrator` thì
  cùng lối còn qua mặt R6.7 (chủ sở hữu cuối) và sự kiện R6.6 của org-and-principals, nên ticket này lấy cả ba luật, một
  revision, một tệp test. Không gộp vào ticket 11: khác yêu cầu (R3.11, R6.7 so với R5.1), khác hàm (các guard và sự
  kiện, không phải `platform.enforce_role_separation_of_duties`), ticket 11 đã mang harness đo và năm cuộc đua, và lane 1
  sắp dựng nó; gộp sẽ phải gate lại 11. Chung với 11 chỉ là bảng `platform.memberships` và tập trigger trên
  `UPDATE OF user_id` (11 thêm `trg_memberships_separation_of_duties` và khóa dòng version ở đầu nó): `Blocked by: 11`,
  để thứ tự khóa (dòng vai trò, khóa tư vấn, dòng tenant trước dòng version) xét trên thân 11 để lại và test của 11
  chạy trong dòng Xong. Nếu sai thì: K1-K4 thành bước 2 mới của ticket 11, gate lại 11.
  Chọn bốn nhánh trên bốn hàm đã có thay vì: `guard_membership_identity` từ chối cả `dw_migrator` khi membership còn lần
  gán (script phải gỡ rồi gán lại, mỗi lần qua mọi luật). Lối đó đơn giản hơn và phủ cả luật sau này, nhưng đổi ô "dưới
  `dw_migrator` → nhận" của RB50 (mục Kiểm soát của spec, nên `Sẵn sàng` của spec về `chưa kiểm` và 08-11 về
  `needs-triage` khi lane 1 đang dựng 08) và đổi câu trả lời của K3 ticket 11. Nếu sai thì: một ticket sau 12 làm việc
  đó, sửa RB50 qua `writing-plan-specs`, và bốn nhánh ở đây thành thừa nhưng vô hại.
  `Yêu cầu:` dẫn RB50 cho K2 vì R6.4, R6.6 của tài khoản dịch vụ là mã của org-and-principals, mà dòng `Yêu cầu:` chỉ
  nhận mã của spec cùng thư mục; K2 đóng đúng lối RB50 để mở (`dw_migrator`). Nếu sai thì: tách K2 thành ticket của
  org-and-principals, `Blocked by` ticket này.
  Ngoài ticket, có chủ ý: lần đổi người không mở công ty `setup` (R3.10): sai về phía đóng, công ty ở lại `setup` tới
  lần kích hoạt hay lần gán kế tiếp. Nếu sai thì: `complete_tenant_setup` trên `UPDATE OF user_id` của `memberships`
  trong revision này.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk một
  subagent, ranh giới 1, 2, 5, 6, vì ticket có migration). `check_plans.py` 24 Đạt. Một HIGH, sửa ở ticket: (1) nhánh
  `role_assignments` của hai guard đọc `memberships.user_id` không khóa, nên một lần gán lên M cạnh lần đổi người của M
  chưa commit được xét theo người cũ, qua cả hai guard, rồi chỉ chờ ở khóa ngoại: nay nhánh đó lấy `FOR KEY SHARE` trên
  M trước khi đọc (khóa mà khóa ngoại đã lấy muộn hơn trong cùng lệnh, như cách của ticket 11), ca (ii) của K1, K2 và
  đột biến (f). MEDIUM, sửa: (2) thêm khóa chủ vào vai trò R mà M mang cạnh đổi M sang người vận hành cùng qua, và cùng
  dạng có sẵn giữa gán R cho người vận hành và thêm khóa chủ vào R (RB39 không có ca đồng thời nào ngoài hai bảng danh
  sách): nhánh khóa chủ của `tenant_role_permissions` và hai nhánh còn lại khi người có trong danh sách khóa dòng vai trò
  `FOR NO KEY UPDATE`, như guard tài khoản dịch vụ, ca (iii), (iv) và đột biến (g); (3) R3.12 chỉ được bỏ ở Comments: nay
  K4, một trigger ràng buộc trên `memberships` gọi hàm ticket 08 để lại, không đổi hàm; (4) "có ít nhất một lần gán" của
  sự kiện R6.6 tính cả lần gán hết hạn và vai trò xóa mềm, như nhánh `role_assignments`. MEDIUM, không sửa, người dựng
  đọc trước: (a) đổi M của chủ `active` cuối sang P `active` cạnh lần đình chỉ P: nhánh `tenant_members` của
  `refuse_losing_the_last_owner` trả sớm khi P chưa giữ `tenant_owner`, không khóa dòng tenant, nên tenant có thể còn 0
  chủ `active`; cùng dạng có sẵn cho lần trao chủ trong một giao dịch (gán P rồi gỡ Q), ngoài lần đổi người; Nếu sai
  thì: nhánh `tenant_members` khóa dòng tenant trước lần trả sớm, một ticket của R6.7. (b) Lần đổi người không có audit
  của cơ sở dữ liệu, và dòng gán giữ `assigned_by`, `assigned_at` của lần gán cho người cũ: như mọi lần ghi vai trò của
  `dw_migrator`, script ghi audit của nó (ADR-0104 (Accepted) mục 6, "exempt by `session_user` and audited"); Nếu sai
  thì: trigger ghi một sự kiện audit lane cho lần đổi người. Sửa sau lượt này không được người đọc mới đọc lại; người
  dựng đọc bước 1 và K1, K2, K4 trước.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới, builder check và boundary walk một
  subagent, ranh giới 1, 2, 5, 6). `check_plans.py` 24 Đạt. 0 CRITICAL, 0 HIGH. MEDIUM, sửa ở thân: (1) lần thêm người
  vào `platform_operators`/`support_staff` cạnh lần thêm khóa chủ vào vai trò R người đó giữ cùng qua (nhánh `ELSE` chỉ
  lấy khóa tư vấn, nhánh `tenant_role_permissions` chỉ lấy dòng R): nay nhánh `ELSE` khóa dòng vai trò của mọi lần gán
  của người đó sau khóa tư vấn, ca (v) và đột biến (h) ở K1, tiêu chí năm ca và tám đột biến. (2) "Một thứ tự khóa cho
  mọi đường" sai ở lúc commit: `check_owner_coverage` của trigger hoãn ghi `platform.tenants` sau dòng version, nên cạnh
  `refuse_losing_the_last_owner` có thể `40P01` (đóng, không lọt); nay bước 1 nói rõ, chủ là ticket 08, không đổi ở đây.
  (3) Dòng Quyết định của spec nói R6.7 đúng cả dưới lần ghi đồng thời, trái MEDIUM (a) lượt trước: sửa câu.
  Quyết định: (4) bên kia của mọi ca đồng thời ở K1, K2 cũng chạy dưới `dw_migrator` (agent, theo ủy quyền 31/10/2026):
  các guard áp cho mọi người ghi, test giữ guard chứ không giữ đường service; các khóa `FOR SHARE` của
  `platform.rbac_refusals` trên lần gán của người gán không nằm trên dòng membership hay dòng vai trò. Nếu sai thì:
  thêm mỗi ca một biến thể dưới `dw_app` với đề xuất được xác nhận trong giao dịch, và thứ tự khóa ghi thêm khóa của
  `rbac_refusals`. MEDIUM, không sửa, người dựng đọc trước: (a) MEDIUM (a) lượt trước (đổi M của chủ `active` cuối sang
  P `active` cạnh đình chỉ P cho 0 chủ `active`) chưa có ticket chủ: phiên điều phối cắt một ticket của R6.7 (nhánh
  `tenant_members` khóa dòng tenant trước lần trả sớm); Nếu sai thì: gộp vào nhánh `refuse_losing_the_last_owner` ở đây.
  (b) MEDIUM (b) lượt trước: repo không có script `dw_migrator` nào đổi `user_id`, nên "script ghi audit" không test
  nào giữ; Nếu sai thì: trigger ghi một sự kiện audit lane cho lần đổi người. (c) K2 không có ca vai trò trọng yếu vì
  `fld.*` trên trường nhạy cảm (vế thứ ba của `platform.role_is_critical`): đột biến thay hàm bằng "`tenant_owner` hay
  khóa `critical`" vẫn xanh; người dựng thêm ca được. (d) Một lệnh UPDATE đổi người nhiều membership khóa dòng vai trò
  theo từng dòng: hai lệnh như thế đồng thời có thể `40P01`, đóng; "không `40P01`" của tiêu chí là cho lệnh một dòng.
  (e) `memberships.role_keys` chứa `platform_admin` đi theo membership khi `user_id` đổi: `dw_migrator` vốn được thêm
  `platform_admin` (RB49), nên không mở lối mới; Nếu sai thì: `guard_legacy_role_columns` bắn cả trên `UPDATE OF
user_id`. (f) Hai lệnh đổi giống hệt đồng thời: lệnh sau thấy `user_id` không đổi, `WHEN` sai, không sự kiện thứ hai;
  không ca riêng. Sửa sau lượt này không được người đọc mới đọc lại; người dựng đọc bước 1 (nhánh `ELSE`, thứ tự khóa)
  và K1 trước.
- 2026-11-06 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
