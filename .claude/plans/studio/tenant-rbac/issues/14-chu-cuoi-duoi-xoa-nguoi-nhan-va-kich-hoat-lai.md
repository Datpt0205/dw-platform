# 14 — Chủ sở hữu cuối dưới lần xóa người nhận và lần kích hoạt lại đồng thời

Status: resolved (2026-11-06, main)
Blocked by: 13
Area: studio
Yêu cầu: R6.7, RB20

## Mục tiêu

R6.7: không thay đổi nào, kể cả "xóa thành viên công ty hay người dùng", làm tenant `active` hay `locked` mất chủ sở hữu
công ty `active` cuối. Sau ticket 13 điều đó đúng cho lần đình chỉ cạnh lần ghi làm người đó thành chủ, nhưng còn hai lối
mà một bên đọc ảnh chụp cũ rồi trả sớm không khóa gì, nên cả hai giao dịch được nhận và tenant còn 0 chủ `active` (MEDIUM
(a) lượt đầu gate ticket 13). (a) Lần xóa dòng công ty của P (hay dòng người dùng của P) cạnh lần trao chủ (gán
`tenant_owner` cho P rồi gỡ của chủ cuối Q): `platform.remove_owner_assignments_first()` xóa lần gán chủ của P theo ảnh
chụp chưa thấy lần trao, rồi lần xóa membership theo dây chuyền chờ lần trao commit, nhưng khi nó gỡ lần gán ấy thì dòng
công ty của P đã mất trong chính giao dịch đó và nhánh `role_assignments` trả sớm. (b) Lần gỡ lần gán `tenant_owner` của Q
(đang `suspended`) cạnh một giao dịch kích hoạt lại Q rồi đình chỉ chủ cuối X: lần gỡ thấy Q chưa `active` và trả sớm, giao
dịch kia đếm Q còn giữ `tenant_owner`. Ticket này cho cả hai bên trả sớm ấy chờ rồi đọc lại: (a) khóa các membership của P
trước câu xóa lần gán, nên chờ mọi lần trao đang mở; (b) bằng cùng khóa `FOR KEY SHARE` có điều kiện mà ticket 13 đặt cho
lần đình chỉ.

## Việc cần làm

Đọc ở `7ad25717` (6/11/2026):

- `platform.refuse_losing_the_last_owner()`: thân gốc ở
  `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:870-932`. Nhánh `role_assignments`
  (`d2b57239ef50_role_administration_and_anti_escalation.py:881-897`) lấy người giữ `v_user` qua membership của
  `OLD.membership_id`; phần chung (`d2b57239ef50_role_administration_and_anti_escalation.py:913-922`) trả sớm khi
  `v_user` NULL, khi người đó không có dòng `platform.tenant_members` `active` (vế `OR TG_TABLE_NAME = 'tenant_members'`
  làm vế này luôn đúng cho nhánh `tenant_members`), hay khi tenant không `active`, `locked` trong ảnh chụp; chỉ sau đó mới
  khóa dòng tenant `FOR UPDATE` (`d2b57239ef50_role_administration_and_anti_escalation.py:923`) rồi đếm. Ticket 12 thêm
  nhánh `memberships` (`v_user := OLD.user_id`, rồi phần chung), ticket 13 sửa nhánh `ELSE` (`tenant_members`); không
  ticket nào sửa phần chung. Thân mới nhất khi ticket này dựng là revision của ticket 13 (tìm bằng
  `grep -l "refuse_losing_the_last_owner" db/migrations/versions/*.py`, mới nhất theo chuỗi `down_revision`).
- `platform.remove_owner_assignments_first()`: thân duy nhất là `_OWNERS_FIRST` ở
  `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:938-957` (`CREATE FUNCTION`, không
  `OR REPLACE`), BEFORE DELETE trên `platform.memberships` và `platform.tenant_members`
  (`d2b57239ef50_role_administration_and_anti_escalation.py:1132-1137`). Không ticket nào sửa hàm này; ticket 12, 13 không
  chạm nó.
- Dây chuyền xóa: `platform.tenant_members.user_id` → `platform.users` `ON DELETE CASCADE`
  (`db/migrations/versions/349080a62e41_tenant_members.py:93-110`); `fk_memberships_tenant_members` `(tenant_id,
user_id)` → `platform.tenant_members` `ON DELETE CASCADE` (`349080a62e41_tenant_members.py:151-153`); và
  `memberships_user_id_fkey` → `platform.users` `ON DELETE CASCADE` (`db/migrations/sql/0001_platform_baseline.sql:736-737`);
  lần gán theo membership `ON DELETE CASCADE` (`db/migrations/versions/b5677d345bc1_tenant_roles.py:159-161`). Lần xóa
  dòng công ty của P: trigger BEFORE trên `tenant_members` chạy, xóa dòng, rồi ở cuối lệnh khóa ngoại xóa membership theo
  dây chuyền, và trigger BEFORE trên `memberships` chạy lại hàm khi dòng công ty đã không còn thấy được trong giao dịch.
  Lần xóa dòng người dùng có hai dây chuyền (qua `tenant_members` và thẳng tới `memberships`); thứ tự hai trigger khóa
  ngoại trên `users` theo tên của chúng, nên lối qua người dùng có thể đã đóng hay còn mở ở commit gốc: đo, không đoán.
- Lần trao chủ bằng INSERT lấy `FOR KEY SHARE` trên membership của P (khóa ngoại của lần gán, và câu đầu các guard của
  ticket 12); lần đổi `role_id` hay `membership_id` lấy `FOR KEY SHARE` trên membership qua guard của ticket 12; lần đổi
  người (ticket 12) lấy `FOR KEY SHARE` trên dòng công ty của người mới (khóa ngoại `fk_memberships_tenant_members`).
  Nên lần xóa thẳng một membership chờ đúng lần trao đang mở ở khóa dòng của chính lệnh xóa rồi xét theo ảnh chụp mới, và
  lần xóa dòng công ty chờ lần đổi người ở khóa dòng; chỉ lần xóa dòng công ty cạnh lần trao bằng lần gán (INSERT hay đổi
  `role_id` trên membership đã có của P) không chờ gì trước khi trigger BEFORE đọc. Lỗ (a) chỉ ở nhánh `tenant_members`
  của `remove_owner_assignments_first`.
- Trạng thái thành viên: `activate_invited_members` chỉ chuyển `invited` sang `active`, "never from `suspended`
  (reopening takes two people, D11)" (`db/migrations/versions/349080a62e41_tenant_members.py:28-31`); lần kích hoạt lại
  từ `suspended` và lần xóa dòng công ty hay người dùng hôm nay là SQL của người vận hành; lần gỡ lần gán và lần xóa
  membership có route `dw_app` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/role_assignments_repo.py:327-350`,
  `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_admin.py:47-56`).
- Thứ tự khóa của ticket 12, 13: dòng của chính lệnh, dòng vai trò, khóa tư vấn, dòng tenant, dòng version
  (`trg_z_bump_access_version` bắn sau cùng trong các trigger AFTER theo dòng, `_BUMPED_TABLES` ở
  `db/migrations/versions/b5677d345bc1_tenant_roles.py:759-767`). `check_owner_coverage` của trigger hoãn ticket 08
  (`db/migrations/versions/a7ca12c36ec7_owner_coverage_per_transaction_and_hold_rule_per_anchor.py:94-128`) ghi
  `platform.tenants` lúc commit bằng UPDATE không đổi khóa (`FOR NO KEY UPDATE`), không xung đột với `FOR KEY SHARE`.
- Mẫu test: R6.7 ở `packages/python/dw_platform/tests/integration/test_role_administration_db.py:733-850`, `plant_world` ở
  `test_role_administration_db.py:192-232`; cuộc đua hai kết nối thật ở
  `packages/python/dw_platform/tests/integration/test_service_principals_db.py:389-440`; hàm gieo
  `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`; tệp test của ticket 13
  (`packages/python/dw_platform/tests/integration/test_last_owner_races.py`, có khi ticket này dựng) mang ca ba bên và
  bộ đếm `40P01`.

Việc:

1. **Migration**: một revision (id hex của `alembic revision`, `down_revision` là head lúc commit, sau revision của
   ticket 13). Mỗi thân nạp bằng `_earlier()` và sửa bằng `_patched()` (neo khớp đúng một lần,
   `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100`; đổi `CREATE FUNCTION` thành
   `CREATE OR REPLACE FUNCTION` như `_replace` ở
   `db/migrations/versions/a7ca12c36ec7_owner_coverage_per_transaction_and_hold_rule_per_anchor.py:77-79`), không chép tay.
    - (a) `platform.remove_owner_assignments_first()`, nạp từ `d2b57239ef50`: chèn trước câu `DELETE FROM
platform.role_assignments a` của thân:

        ```sql
        IF TG_TABLE_NAME = 'tenant_members' THEN
            PERFORM 1 FROM platform.memberships m
            WHERE m.tenant_id = (v_old->>'tenant_id')::uuid AND m.user_id = (v_old->>'user_id')::uuid
            ORDER BY m.id
            FOR UPDATE;
        END IF;
        ```

        Vì sao từng phần:
        - Mọi lần ghi làm P thành chủ giữ tới commit một khóa trên dòng của P: lần gán mới hay lần đổi `role_id`,
          `membership_id` giữ `FOR KEY SHARE` trên membership của P (khóa ngoại của lần gán, câu đầu các guard của ticket
          12); lần đổi người và lần tạo membership mới cho P giữ `FOR KEY SHARE` trên dòng công ty của P (khóa ngoại
          `fk_memberships_tenant_members`), mà lệnh xóa đã khóa trước khi trigger BEFORE chạy; lần kích hoạt lại P giữ chính
          dòng công ty đó. `FOR UPDATE` trên các membership của P xung đột với `FOR KEY SHARE`, nên lần xóa chờ mọi lần trao
          đang mở, và câu `DELETE` theo sau, câu mới của hàm `VOLATILE` ở READ COMMITTED, lấy ảnh chụp mới: nó thấy mọi lần
          gán chủ của P, kể cả trên membership thứ hai (K1 (iii)) hay một lần gán vừa thêm trong lúc câu `DELETE` cũ còn
          chờ một dòng lần gán (K1 (iv)), xóa chúng khi dòng công ty còn thấy được, và nhánh `role_assignments` đếm rồi từ
          chối. Ngược lại, lần trao tới sau chờ ở khóa ngoại của nó tới khi lần xóa commit, rồi thấy membership đã mất.
        - Đúng các dòng mà dây chuyền xóa sẽ khóa `FOR UPDATE` ở cuối chính lệnh này, nên không thêm khóa mới, chỉ lấy sớm
          hơn, theo `ORDER BY m.id`; không khóa dòng tenant, nên không đổi gì với khóa ngoại tới tenant, với ticket 08, hay
          với lần xóa hai chủ cuối (hai người, hai tập membership rời nhau, rồi xếp hàng ở `FOR UPDATE` của nhánh
          `role_assignments`, K3). Mọi trạng thái tenant, kể cả `setup` (ticket 15) và `offboarding` (dây chuyền vốn khóa
          các dòng ấy).
        - Chỉ nhánh `tenant_members`: lần xóa thẳng một membership đã khóa dòng ấy bằng chính lệnh xóa trước trigger BEFORE,
          nên đã chờ mọi lần trao trên nó (ca đối chứng của K1 giữ điều đó).
        - Bảo đảm là của READ COMMITTED, như bước 1 của ticket 13.

    - (b) `platform.refuse_losing_the_last_owner()`, nạp từ revision của ticket 13: chỉ phần chung đổi. Neo là cả khối
      `IF v_user IS NULL OR NOT EXISTS (...) OR NOT EXISTS (...) THEN RETURN NULL; END IF;` đứng ngay trước câu `PERFORM
1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;` (khẳng định khối khớp đúng một lần trong thân của 13). Gọi
      `<người giữ active>` là đúng chuỗi câu con thứ nhất của khối (`SELECT 1 FROM platform.tenant_members tm WHERE ...
AND (tm.status = 'active' OR TG_TABLE_NAME = 'tenant_members')`), lấy một lần trong Python từ neo và dùng hai chỗ,
      không gõ lại. Thay khối bằng:

        ```sql
        IF v_user IS NULL OR NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = v_tenant AND t.status IN ('active', 'locked')
        ) THEN
            RETURN NULL;
        END IF;
        IF NOT EXISTS (<người giữ active>) THEN
            IF NOT EXISTS (
                SELECT 1 FROM platform.tenant_members tm
                WHERE tm.tenant_id = v_tenant AND tm.user_id = v_user
            ) THEN
                RETURN NULL;
            END IF;
            PERFORM 1 FROM platform.tenants
            WHERE id = v_tenant AND status IN ('active', 'locked') FOR KEY SHARE;
            IF TG_TABLE_NAME = 'role_assignments' THEN
                SELECT m.user_id INTO v_user FROM platform.memberships m
                WHERE m.tenant_id = OLD.tenant_id AND m.id = OLD.membership_id;
            END IF;
            IF v_user IS NULL OR NOT EXISTS (<người giữ active>) THEN
                RETURN NULL;
            END IF;
        END IF;
        ```

        Vì sao từng phần:
        - Ba điều kiện trả sớm cũ giữ nguyên nghĩa; chỉ điều kiện "người giữ chưa `active`" thôi trả ngay. Nhánh
          `tenant_members` không đổi hành vi (vế `OR TG_TABLE_NAME = 'tenant_members'`).
        - Người giữ không có dòng công ty (dòng đã xóa trong chính giao dịch, dây chuyền xóa): trả như hôm nay; lối đó do
          (a) đóng ở trigger BEFORE.
        - Người giữ có dòng công ty mà chưa `active` (`suspended`, `invited`): một giao dịch đang mở có thể vừa kích hoạt
          lại người đó vừa gỡ chủ khác, và giữ dòng tenant `FOR UPDATE`; `FOR KEY SHARE` chờ nó, câu đọc lại thấy người
          giữ đã `active`, và phần chung đếm 0 rồi từ chối. Chỉ lấy khóa khi người giữ chưa `active` trong ảnh chụp đầu:
          lần gỡ lần gán của chủ `active` đi thẳng tới `FOR UPDATE` như hôm nay (K3).
        - Ở nhánh `role_assignments`, sau khóa đọc lại cả người của membership, không chỉ trạng thái của `v_user` cũ: giao
          dịch đang mở có thể đã đổi người của chính membership đó (ticket 12, `dw_migrator`) từ Q chưa `active` sang P
          `active` rồi gỡ chủ cuối; lệnh DELETE lần gán không qua guard nào khóa membership, nên chỉ câu đọc lại thấy P
          (K2 (iii)). Câu đọc là đúng câu lấy `v_user` của nhánh `role_assignments` (lấy từ thân trong Python, không gõ
          lại). Nhánh `memberships` của 12 lấy `v_user := OLD.user_id` trên dòng chính lệnh đã khóa, nên không đọc lại.
        - Phần chung phủ cả nhánh `role_assignments` lẫn nhánh `memberships` của ticket 12 (người cũ chưa `active` cạnh
          giao dịch kích hoạt lại người đó rồi đình chỉ chủ cuối, biến thể của K2).

    Thứ tự khóa: lần xóa dòng công ty: dòng `tenant_members`, các dòng membership của P (`FOR UPDATE`, `ORDER BY id`,
    ở (a)), các dòng lần gán, dòng tenant `FOR UPDATE` (nhánh `role_assignments`, khi P là chủ), rồi trigger AFTER của
    `tenant_members` theo tên: dây chuyền khóa ngoại (`RI_ConstraintTrigger_a_*`) trước `trg_z_bump_access_version`
    (dòng version); lần gỡ lần gán: dòng lần gán, các khóa guard của ticket 12, dòng tenant (`FOR KEY SHARE` ở (b), rồi
    `FOR UPDATE`), dòng version: "dòng tenant trước dòng version" như ticket 12, 13. (a) không lấy khóa mới nào, chỉ lấy
    sớm các khóa dây chuyền vốn lấy, nên không có dạng `40P01` mới; ca xen giữa của K1 xếp hàng. Dạng `40P01` mới của
    (b), có chủ ý, mọi dạng đều đóng (một bên bị hủy, không bên nào lọt):
    - ca xen giữa của K2: câu 1 của giao dịch kích hoạt lại Q giữ dòng version; lần gỡ lần gán của Q giữ `FOR KEY SHARE`
      rồi chờ dòng version; câu 2 chờ ở `FOR UPDATE`. Hôm nay cả hai được nhận và tenant còn 0 chủ;
    - giao dịch nhiều câu đã giữ dòng version rồi lấy dòng tenant `FOR UPDATE`, xen giữa là lần gỡ lần gán
      `tenant_owner` của một người chưa `active` bất kỳ ở cùng tenant: cùng dạng (4) lượt đầu gate ticket 13. Dạng này có
      cả trong API: một lần ghi của `role_assignments_repo` gỡ nhiều lần gán trong một giao dịch (lần gán thường lấy dòng
      version trước, lần gán `tenant_owner` của chủ `active` lấy `FOR UPDATE` sau) cạnh lần gỡ `tenant_owner` của người
      được mời qua cùng route; `role_write_refusal` chỉ ánh xạ `IntegrityError`, nên bên bị hủy nhận 500 (quyết định ở
      Comments);
    - hai bên cùng giữ `FOR KEY SHARE` rồi cùng nâng lên `FOR UPDATE` sau một lần chờ chung (hai người giữ cùng được kích
      hoạt lại). "Không `40P01`" của tiêu chí là cho lệnh một dòng như các ca của K. Dạng của ticket 08 không rộng thêm
      (K4 (ii)).

    Không bảng, cột, quyền vai, hàm mới, trigger mới hay route, nên `test_rls_coverage.py`, `test_privileges.py` và
    `test_offboarding_coverage.py` không đổi và phải xanh (offboarding xóa ở tenant `offboarding`: (a) khóa các membership mà dây chuyền vốn khóa, (b) ngoài vế trạng thái).
    Downgrade dựng lại hai thân trước (từ chính các module `_earlier`), cũng qua `CREATE OR REPLACE` (thân của
    `d2b57239ef50` là `CREATE FUNCTION`).

2. **Harness**: nếu tệp test của ticket 13 có hàm cuộc đua ba bên và bộ đếm `40P01`, chuyển chúng (cùng `_blocked`,
   `_until`) vào `packages/python/dw_platform/src/dw_platform/testing/races.py` và cho tệp của 13 import từ đó, không chép
   bản thứ hai; nếu không có, viết chúng ở module đó theo dạng `_race` của `test_service_principals_db.py:410-440` (bên
   thứ nhất giữ giao dịch mở, các bên sau chạy trong task tới khi chờ khóa hay đã xong, bên thứ nhất commit; không ngủ cố
   định). Không sửa `test_service_principals_db.py` hay `test_role_write_races.py`.
3. **Test** (integration, tệp mới `packages/python/dw_platform/tests/integration/test_owner_count_races.py`): mỗi ca trên
   tenant gieo mới dưới `dw_migrator`, chủ sở hữu và người như `plant_world`; mọi bên dưới `dw_migrator` (luật chủ cuối áp
   cho mọi người ghi, quyết định (4) lượt xác nhận gate ticket 12). Harness đếm SQLSTATE `40P01` riêng, phải là 0 ở mọi ca
   trừ ca xen giữa. Mỗi ca xen giữa có ba bước (bên A câu 1; bên B trong một task tới khi chờ khóa; A câu 2 rồi commit),
   bắt `DBAPIError` ở câu 2, ở lần commit của A và ở task của B, và khẳng định đúng một bên bị hủy, không khẳng định bên
   nào. Sau mỗi ca: `platform.active_tenant_owners` của tenant có ít nhất một người; mỗi lần từ chối 23514 khẳng định tên
   ràng buộc `ck_role_assignments_last_owner` và trạng thái (dòng công ty, lần gán) của bên bị từ chối không đổi.
4. `reviewing-feature-security` (ranh giới 1, 2, 6; 3 và 5 không áp: không đường agent hay tool, lần xóa và lần kích hoạt
   lại là SQL của người vận hành và audit của nó thuộc script, ADR-0104 (Accepted) mục 6), `mutations/14.yaml` một đột
   biến mỗi dòng ở cột "Đột biến" dưới đây, không chạy `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng
   tay. Độ trễ: câu khóa của (a) chỉ chạy khi một dòng công ty bị xóa, không route nào làm; phần chung đổi ở (b) chạy ở
   mọi lần gỡ lần gán `tenant_owner` (thêm một câu đọc khi người giữ `active`, thêm câu khóa và hai câu đọc khi chưa
   `active`), trong đó có route `dw_app` gỡ lần gán (`role_assignments_repo.py:327-350`) và route xóa membership
   (`membership_admin.py:47-56`): đo P50/P95/P99 của hai route đó với một lần gán `tenant_owner` ở lúc đóng hàng đợi
   (`.claude/rules/latency.md`).

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                                                                        | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Đột biến (`mutations/14.yaml`)                                                                                                                                                                                                                                                                       |
| --- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | Xóa dòng công ty hay người dùng của người nhận cạnh lần trao chủ không làm mất chủ `active` cuối | Tenant `active` (rồi, ca riêng, `locked`), Q là chủ `active` duy nhất; P là thành viên công ty `active` có membership M_P ở workspace `main`, không mang `tenant_owner`. Bên A một giao dịch hai câu: gán `tenant_owner` lên M_P, rồi gỡ lần gán `tenant_owner` của Q. Bên B `DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :p`. (i) A trọn hai câu rồi B → B bị từ chối với 23514, P còn dòng công ty và là chủ `active`. (ii) B trước rồi A → A bị từ chối ở câu 1 (lần gán lên membership đã xóa; khóa ngoại của lần gán, 23503 theo phân tích, SQLSTATE đo được ghi ở Comments), lần gán của Q không đổi: ca hồi quy, đóng ở commit gốc. (iii) P đã là chủ qua M_P1 và có M_P2 ở workspace thứ hai; A gán `tenant_owner` lên M_P2 rồi gỡ Q; thứ tự (i) → B bị từ chối với 23514. (iv) Ba bên: P là chủ `active` duy nhất qua M_P1 (lần gán A_P1) và có M_P2 không mang chủ; bên C giữ `SELECT 1 FROM platform.role_assignments WHERE id = :a_p1 FOR SHARE`; B chạy tới khi chờ khóa (câu xóa lần gán chờ A_P1); bên T gán `tenant_owner` lên M_P2 chạy tới khi chờ hay xong, xong thì commit; C commit; rồi B, rồi T xong và commit → B bị từ chối với 23514, P còn là chủ (dưới đột biến (a) T xong trước, B xóa A_P1 theo ảnh chụp cũ, đếm được P qua lần gán của T, rồi dây chuyền xóa nó: 0 chủ). Xen giữa (A câu 1, B tới khi chờ khóa, A câu 2 rồi commit): B chờ ở membership của P rồi bị từ chối với 23514, A nhận, không `40P01`. Biến thể người dùng: B `DELETE FROM platform.users WHERE id = :p`, thứ tự (i) → B bị từ chối với 23514 (kết quả ở commit gốc ghi ở Comments). Đối chứng: B xóa dòng công ty của R (`active`, không phải chủ) cạnh A, thứ tự (i) → cả hai nhận; B xóa thẳng M_P cạnh lần trao bằng đổi `role_id` (A: đổi lần gán khác của M_P sang `tenant_owner`, rồi gỡ Q), thứ tự (i) → B bị từ chối với 23514 (đóng nhờ khóa trên M_P, ca hồi quy) | (a) bỏ câu khóa membership của (a) ((i), (iii), (iv) và ca xen giữa đỏ: hai bên nhận, 0 chủ); (b) đặt câu khóa của (a) sau câu `DELETE` của thân ((i) đỏ: câu xóa đã đọc ảnh chụp cũ); (c) `FOR SHARE` thay `FOR UPDATE` ở câu khóa của (a) ((i) đỏ: `FOR SHARE` không xung đột với `FOR KEY SHARE`) |
| K2  | Gỡ lần gán của chủ chưa `active` cạnh lần kích hoạt lại người đó không làm mất chủ `active` cuối | Tenant `active` (rồi, ca riêng cho thứ tự (i), `locked`), X là chủ `active` duy nhất; Q giữ `tenant_owner` qua M_Q và `suspended`. Bên A một giao dịch hai câu: kích hoạt lại Q (`UPDATE platform.tenant_members SET status = 'active'`), rồi đình chỉ X. Bên B gỡ lần gán `tenant_owner` của Q. (i) A trọn hai câu rồi B → B bị từ chối với 23514, Q còn giữ `tenant_owner`. (ii) B trước rồi A → câu 2 của A bị từ chối với 23514 (dòng version xếp câu 1 của A sau B): ca hồi quy, đóng ở commit gốc. Xen giữa (A câu 1, B tới khi chờ khóa, A câu 2): đúng một bên bị hủy, tenant còn đúng một chủ `active`. Biến thể nhánh `memberships`: B `dw_migrator` đổi M_Q sang R (`invited`, chưa có membership ở workspace đó), thứ tự (i) → B bị từ chối với 23514, M_Q giữ người Q. (iii) Biến thể đổi người trong A: Q `suspended` giữ `tenant_owner` qua M; A một giao dịch hai câu dưới `dw_migrator`: đổi M sang P (`active`, chưa có membership ở workspace đó), rồi đình chỉ X; B gỡ lần gán `tenant_owner` trên M, thứ tự (i) → B bị từ chối với 23514. Đối chứng: B gỡ lần gán `tenant_owner` của S (`suspended`, khác Q) cạnh A, thứ tự (i) → cả hai nhận (ở ca xen giữa cặp này thuộc dạng `40P01` thứ hai của bước 1, không chạy)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | (a) bỏ câu `PERFORM ... FOR KEY SHARE` của (b) ((i) và biến thể đỏ); (b) bỏ câu đọc lại thứ hai của (b), trả sau khóa ((i) đỏ); (c) bỏ câu đọc lại người của membership sau khóa ((iii) đỏ)                                                                                                          |
| K3  | Hai khóa thêm không làm hai lần mất hai chủ khóa chết                                            | Ba bên, tenant `active` có đúng hai chủ `active` Q1, Q2; bên C chỉ chạy `SELECT 1 FROM platform.tenants WHERE id = :t FOR NO KEY UPDATE` và giữ giao dịch mở (xung đột với `FOR UPDATE`, không với `FOR KEY SHARE`, nên dưới đột biến hai bên lấy khóa chia sẻ ngay và cùng nâng trước lần commit của C: đỏ tất định). (i) Xóa dòng công ty của Q1 và của Q2 ở hai kết nối, mỗi bên chạy tới khi chờ khóa; C commit → đúng một trong hai bị từ chối với 23514, bên kia nhận, không `40P01`, tenant còn đúng một chủ `active`. (ii) Cùng ca với hai lần gỡ lần gán `tenant_owner` của Q1 và của Q2                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | (b) câu `PERFORM ... FOR KEY SHARE` của (b) không điều kiện, trước câu đọc người giữ ((ii) đỏ). (i) là ca hồi quy cho (a): hai người, hai tập membership rời nhau, không đột biến riêng                                                                                                              |
| K4  | Hai khóa thêm không chặn khóa ngoại, và không thêm `40P01` cạnh ticket 08                        | Tenant `active`. (i) Bên thứ nhất giữ mở (i-a) lần xóa dòng công ty của R (không phải chủ), hay (i-b) lần gỡ lần gán `tenant_owner` của S (`suspended`); bên thứ hai INSERT một dòng `platform.workspaces` của tenant → xong trước lần commit của bên thứ nhất (harness khẳng định điều đó, không chỉ "không bị từ chối"). (ii) Gieo và khẳng định trước ca như K4 (ii) của ticket 13 (`owner_coverage_low_since` NULL, `platform.checker_candidates(t, 'platform.roles.write', NULL)` đếm đúng 2, mọi khóa khác của `platform.owner_permission_keys()` ít nhất 2); bên thứ nhất gỡ lần gán `platform.roles.write` của người giữ không phải chủ, đưa số đếm về 1, giữ mở; bên thứ hai (ii-a) xóa dòng công ty của R, hay (ii-b) gỡ lần gán `tenant_owner` của S, chạy tới khi chờ dòng version; bên thứ nhất commit → cả hai nhận, 0 `40P01`, đúng một sự kiện `platform.tenant.owner_coverage_low`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | (a) khóa dòng tenant `FOR UPDATE` thay câu khóa membership của (a), phương án đã bỏ ((i-a) chờ, (ii-a) `40P01`); (b) `FOR NO KEY UPDATE` thay `FOR KEY SHARE` ở (b) ((ii-b) `40P01`)                                                                                                                 |

## Tiêu chí chấp nhận

- [x] R6.7 (RB20): K1, lần xóa dòng công ty của P và lần trao chủ hai câu (gán P, gỡ Q) đồng thời, ở tenant `active` và
      `locked`, cho đúng bên thứ hai bị từ chối ở cả hai thứ tự (23514 `ck_role_assignments_last_owner` cho lần xóa ở thứ
      tự (i), ca (iii), ca ba bên (iv) và ca xen giữa), không `40P01`; biến thể xóa dòng người dùng thứ tự (i) cho
      23514; hai ca
      đối chứng như bảng; sai nếu một ca kết thúc với 0 chủ `active`, ca xóa người không phải chủ bị từ chối, hay một
      trong ba đột biến của K1 vẫn xanh. Ở commit gốc (sau ticket 13) thứ tự (i), ca (iii), (iv) và ca xen giữa nhận cả hai bên
      và tenant còn 0 chủ `active`; biến thể người dùng có thể đã đóng ở commit gốc (thứ tự trigger khóa ngoại trên
      `users`), kết quả đo ghi ở Comments và ca giữ làm hồi quy.
- [x] R6.7 (RB20): K2, lần gỡ lần gán `tenant_owner` của Q `suspended` và giao dịch kích hoạt lại Q rồi đình chỉ chủ cuối
      X đồng thời, ở tenant `active` và (thứ tự (i)) `locked`, cho đúng bên thứ hai 23514 ở cả hai thứ tự, không `40P01`;
      biến thể (iii) (A đổi M của Q sang P rồi đình chỉ X, B gỡ lần gán trên M) cho B 23514; ở ca xen giữa đúng một bên bị hủy; biến thể
      đổi người M_Q thứ tự (i) cho 23514; sai nếu một ca kết thúc với 0 chủ `active`, ca đối chứng bị từ chối, hay một
      trong ba đột biến của K2 vẫn xanh. Ở commit gốc thứ tự (i), hai biến thể và ca xen giữa nhận cả hai bên.
- [x] R6.7 (RB20): K3, ở hai ca ba bên đúng một trong hai lần mất chủ bị từ chối với 23514 sau lần commit của C, không
      `40P01`; sai nếu một bên `40P01` hay cả hai nhận, hay đột biến của K3 vẫn xanh.
- [x] R6.7 (RB20): K4, lần xóa dòng công ty người không phải chủ và lần gỡ lần gán `tenant_owner` của người
      `suspended` đang mở không chặn lần INSERT có khóa ngoại tới tenant, và cạnh lần gỡ hạ người giữ
      `platform.roles.write` xuống dưới hai cả hai được nhận, 0 `40P01`, đúng một sự kiện
      `platform.tenant.owner_coverage_low`; sai nếu bên thứ hai chờ ở (i), có `40P01` ở (ii), hay một trong hai đột biến
      của K4 vẫn xanh.
- [x] Xong: `uv run python -m pytest packages/python/dw_platform/tests/integration/test_owner_count_races.py packages/python/dw_platform/tests/integration/test_last_owner_races.py packages/python/dw_platform/tests/integration/test_role_administration_db.py packages/python/dw_platform/tests/integration/test_membership_change_of_person.py packages/python/dw_platform/tests/integration/test_role_write_races.py packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py` xanh.

## Nguồn

- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:870-932`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:881-897`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:913-923` (R6.7); `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:938-957`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1132-1137` (`remove_owner_assignments_first`).
- `db/migrations/versions/349080a62e41_tenant_members.py:93-110`, `db/migrations/versions/349080a62e41_tenant_members.py:151-153`, `db/migrations/sql/0001_platform_baseline.sql:736-737`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:159-161` (dây chuyền xóa); `db/migrations/versions/349080a62e41_tenant_members.py:28-31` (kích hoạt lại).
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:759-767` (`_BUMPED_TABLES`); `db/migrations/versions/a7ca12c36ec7_owner_coverage_per_transaction_and_hold_rule_per_anchor.py:77-79`, `db/migrations/versions/a7ca12c36ec7_owner_coverage_per_transaction_and_hold_rule_per_anchor.py:94-128` (ticket 08); `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100` (`_earlier`, `_patched`); bước 1 của ticket 12 và 13.
- `packages/python/dw_platform/tests/integration/test_role_administration_db.py:192-232`, `packages/python/dw_platform/tests/integration/test_role_administration_db.py:733-850`, `packages/python/dw_platform/tests/integration/test_service_principals_db.py:389-440`, `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`.
- Spec: R6.7, RB20; ADR-0104 (Accepted) mục 6 ("keeps one active `tenant_owner`, cascades included"), Amendments 2026-11-03 (`locked`); MEDIUM (a) lượt đầu gate ticket 13.

## Comments

- 2026-11-06 (agent, theo ủy quyền 31/10/2026): cắt từ MEDIUM (a) lượt đầu gate ticket 13. Đã dựng lại hai lối trên code
  ở `7ad25717` cộng thân của ticket 12, 13 như đặc tả, với hai hay ba kết nối: (a) thật cho lần xóa dòng công ty (trigger
  BEFORE trên `tenant_members` không chờ gì, dây chuyền tới membership chờ lần trao rồi xét khi dòng công ty đã mất), còn
  lần xóa thẳng membership đã đóng (khóa dòng của chính lệnh xóa); (b) thật ở thứ tự (i) và ca xen giữa, thứ tự (ii) đã
  đóng nhờ dòng version. `Blocked by: 13`: (b) sửa phần chung của `refuse_losing_the_last_owner`, mà 13 thay bằng
  `CREATE OR REPLACE`; một revision dựng từ thân trước 13 sẽ xóa nhánh của 13. (a) sửa một hàm khác,
  `remove_owner_assignments_first`, không ticket nào chạm, nên tự nó không cần chờ 13; giữ một revision cho cả hai vì
  cùng một luật, cùng một dạng khóa và cùng tệp test. Nếu sai thì: (a) tách thành ticket không chặn, chỉ chờ 12 (thứ tự
  khóa với guard của 12).
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk một
  subagent, ranh giới 1, 2, 6; 3, 5 không áp). Một HIGH, sửa ở ticket: (1) khi P đã là chủ qua M_P1, lần trao thêm lần gán
  chủ lên M_P2 rồi gỡ Q, thì lần xóa dòng công ty của P đi thẳng (không khóa ở (a)), câu `DELETE` chỉ xóa lần gán của M_P1,
  nhánh `role_assignments` chờ lần trao rồi đếm được chính P qua M_P2, và lần gán của M_P2 bị xóa sau theo dây chuyền khi
  dòng công ty đã mất: 0 chủ. Nay nhánh P đã là chủ của (a) khóa dòng tenant `FOR UPDATE` trước câu `DELETE` (không
  `FOR KEY SHARE`, để K3 xếp hàng), K1 (iii) và đột biến K1 (c); đột biến K3 (a) thành `FOR KEY SHARE` ở nhánh đó.
  MEDIUM, sửa: (2) K2 thêm ca `locked` cho câu khóa của (b); (3) ca đối chứng R của K1 chạy thứ tự (i), vì ở ca xen giữa
  nó là dạng `40P01` thứ ba; (4) đột biến K3 có thể không đỏ ở một lần chạy: chạy vài lần như MEDIUM (b) lượt xác nhận
  gate 13; (5) K1 (ii) nêu lỗi dự kiến (khóa ngoại, 23503) và khẳng định lần gán của Q không đổi, không đòi 23514; (6)
  downgrade cũng qua `CREATE OR REPLACE`; (7) tiêu chí K1 nói rõ biến thể người dùng có thể đã đóng ở commit gốc.
  MEDIUM, không sửa, người dựng đọc trước: (a) bản `_race` cũ ở `test_service_principals_db.py` và `race` ở
  `test_role_write_races.py` còn là bản sao của harness (failure-modes #2): no owner yet; gom chúng vào
  `dw_platform.testing.races` cần sửa tệp test của lane khác. (b) Lần trao bằng đổi `membership_id` (chuyển lần gán của Q
  sang M_P) cạnh lần xóa dòng công ty của P đi cùng cơ chế K1 mà không có ca riêng; người dựng thêm được. (c) Lần xóa
  dòng người dùng là thành viên nhiều tenant, hai lệnh như thế đồng thời, có thể `40P01` theo thứ tự dây chuyền: đóng,
  không ca. (d) Lần xóa ở tenant B không chặn lần trao ở tenant A (khóa theo dòng của từng tenant): không ca riêng, như (c)
  lượt đầu gate 13. (e) Lane offboarding xóa hàng loạt dòng công ty ở tenant `offboarding`: câu đọc chủ của (a) chạy mỗi
  dòng mà không khóa; không đáng đo. Sửa sau lượt này được lượt xác nhận đọc lại.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới, builder check và boundary walk một
  subagent). Một HIGH, sửa ở ticket: (1) câu đọc lại của (b) dùng `v_user` đọc trước lần chờ, nên A đổi M (của Q
  `suspended`, mang `tenant_owner`) sang P `active` rồi đình chỉ chủ cuối X, cạnh B gỡ lần gán trên M, vẫn để 0 chủ (lệnh
  DELETE lần gán không qua guard nào khóa M): nay nhánh `role_assignments` đọc lại người của membership sau khóa, K2
  (iii) và đột biến K2 (c). MEDIUM, sửa: (2) dạng `40P01` mới của nhánh P đã là chủ (dòng tenant trước dòng lần gán) cạnh
  lần gỡ thẳng một lần gán của P, nêu ở danh sách; (3) K3 dàn tất định: bên C chỉ giữ `FOR NO KEY UPDATE` trên dòng
  tenant, hai chủ, nên dưới đột biến hai bên lấy khóa chia sẻ ngay rồi cùng nâng; bỏ ghi chú "chạy vài lần". LOW, sửa:
  (4) ca đối chứng S của K2 chạy thứ tự (i). Không sửa, người dựng đọc trước: (a) biến thể nhánh `memberships` cần
  trigger `ck_role_assignments_last_owner AFTER UPDATE OF user_id` trên `memberships` mà bước 1 của ticket 12 đặt; bản
  12 lane 1 đang dựng phải có nó (đối chiếu khi dựng). (b) Vế `status IN ('active', 'locked')` của hai câu khóa không ca
  nào giữ, như MEDIUM (a) lượt xác nhận gate 13; ticket 15 đổi chính vế đó và có ca của nó. (c) Không ca dưới `dw_app`
  (quyền DELETE trên `tenant_members` cho offboarding): trigger áp mọi người ghi, quyết định (4) gate 12 giữ. Sửa sau
  lượt này không được người đọc mới đọc lại; người dựng đọc bước 1 (b) và K2, K3 trước.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận thứ hai (người đọc mới). Một HIGH, sửa ở ticket: (1) khóa
  dòng tenant ở (a) chỉ chặn lần trao có gỡ chủ khác: P là chủ cuối qua M_P1, câu `DELETE` của lần xóa chờ một dòng lần
  gán do bên C giữ (`rbac_refusals` khóa `FOR SHARE` lần gán của chính người ghi, hay một `SELECT ... FOR SHARE`), trong
  lúc đó T gán thêm chủ cho P lên M_P2 và commit; câu `DELETE` theo ảnh chụp cũ chỉ xóa A_P1, nhánh `role_assignments`
  đếm được P qua M_P2, và dây chuyền xóa lần gán đó sau, không xét: 0 chủ. Nay (a) khóa các membership của P
  `FOR UPDATE ORDER BY id` trước câu `DELETE` (đúng khóa dây chuyền vốn lấy, xung đột với `FOR KEY SHARE` mà mọi lần trao
  giữ trên membership hay dòng công ty của P), thay cả hai câu khóa dòng tenant của (a): không khóa mới, không dạng
  `40P01` mới (ca xen giữa của K1 nay xếp hàng), không tùy trạng thái tenant. K1 (iv) ba bên, đột biến K1 đổi theo; K3 (i)
  thành ca hồi quy cho (a); đột biến K4 (a) thành phương án đã bỏ. Nếu sai thì: (a) về hai câu khóa dòng tenant của lượt
  trước và K1 (iv) thành rủi ro ghi ở Comments. MEDIUM, sửa: (2) phần chung đổi ở (b) chạy dưới route `dw_app` gỡ lần
  gán và xóa membership: hai route đó vào bước đo độ trễ lúc đóng hàng đợi; dạng `40P01` của (b) xảy ra cả trong API
  (lần ghi gỡ nhiều lần gán cạnh lần gỡ `tenant_owner` của người được mời). Quyết định (agent, theo ủy quyền 31/10/2026):
  bên bị hủy nhận 500 như mọi lỗi không ánh xạ, không thêm ánh xạ hay thử lại trong ticket này: dạng đó cần hai quản trị
  viên cùng ghi vai trò ở một tenant, một bên gỡ cả chủ `active` lẫn lần gán thường, và nó đóng. Nếu sai thì:
  `role_write_refusal` ánh xạ SQLSTATE `40P01` thành 409 có thể thử lại, một ticket của route quản trị vai trò. LOW, sửa:
  (3) thứ tự khóa: dây chuyền khóa ngoại bắn trước dòng version; (4) bước độ trễ không còn nói "không thêm câu". Sửa sau
  lượt này không được người đọc mới đọc lại (hai lượt chạy lại mỗi phiên bản đã dùng); người dựng đọc bước 1 (a), K1
  (iv) và K3 trước.
- 2026-11-06 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): dựng xong, `resolved`. Revision `a6b8f3702570` (trên `596062dfa2d0`):
  (a) `remove_owner_assignments_first()` từ `_OWNERS_FIRST` của `d2b57239ef50` (`CREATE OR REPLACE`), khóa các membership
  của người trên dòng công ty `FOR UPDATE` theo `id` trước câu `DELETE`; (b) phần chung của `refuse_losing_the_last_owner()`
  từ thân ticket 13, câu con "người giữ `active`" và câu đọc người của membership lấy một lần trong Python và dùng hai
  chỗ; downgrade dựng lại hai thân. Harness: `packages/python/dw_platform/src/dw_platform/testing/races.py` (`race`,
  `waiting_pair` ba bên, `interleaved`, `until_waiting`, `sqlstate`), tệp test của ticket 13 nay import từ đó, không còn
  bản thứ hai. Test: `packages/python/dw_platform/tests/integration/test_owner_count_races.py`, 22 ca. Số đo cần ghi:
  K1 (ii) (lần trao sau lần xóa) bị từ chối ở câu 1 với SQLSTATE 23503 (khóa ngoại của lần gán), đo được như phân tích;
  biến thể xóa dòng người dùng đã đóng ở commit gốc: dưới đột biến K1 (a) (bỏ khóa membership) test của nó vẫn xanh, vì
  dây chuyền thẳng `users` → `memberships` chạy trước dây chuyền qua `tenant_members`, nên trigger trên `memberships` xét
  khi dòng công ty còn; test giữ làm hồi quy. Gate nhanh: ruff, format, mypy (tệp của ticket sạch; 8 lỗi ở hai tệp test
  của làn khác: `dw_agent_runtime/tests/unit/test_field_security_tools.py`, `dw_studio/tests/unit/test_object_tools.py`),
  integration của dòng Xong 273 xanh. Phá thử bằng tay cả 9 đột biến của `mutations/14.yaml`: cả 9 đỏ đúng lý do (K1
  hai bên nhận và 0 chủ; K2 bên thứ hai được nhận; K3 (b) `40P01`; K4 (a) chờ hay `40P01`, (b) `40P01`).
  `reviewing-feature-security`: ranh giới 1 (khóa đúng membership của người đó trong `v_old.tenant_id`, đúng dòng tenant
  `v_tenant`; K4 (i) không chặn khóa ngoại), 2 (mọi người ghi kể cả `dw_migrator`), 6 (dây chuyền xóa là lối cuối, test ở
  tầng database); 3, 5 không áp như ticket ghi; 4 không áp. Độ trễ: P50/P95/P99 của route gỡ lần gán và route xóa
  membership với một lần gán `tenant_owner` đo lúc đóng hàng đợi như bước 4 ghi. Không khác gì khác so với ticket.
