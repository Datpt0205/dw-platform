# 15 — Công ty `setup` mở với ít hơn hai chủ dưới lần mất chủ đồng thời

Status: resolved (2026-11-06, main)
Blocked by: 14
Area: studio
Yêu cầu: R3.10, R6.7, RB20, RB38

## Mục tiêu

R3.10: một tenant `setup` sang `active` khi và chỉ khi số thành viên công ty `active` giữ `tenant_owner` lên hai, và R6.7:
một tenant `active` không còn chủ `active` nào bị từ chối. Cả hai đúng cho mỗi lần ghi xét một mình, và hai lần kích hoạt
đồng thời xếp hàng ở dòng tenant, nhưng không cho một lần kích hoạt cạnh một lần mất chủ: ở tenant `setup`
`platform.refuse_losing_the_last_owner()` trả sớm trước khi khóa gì (tenant không `active`, `locked` trong ảnh chụp của
nó), và các khóa `FOR KEY SHARE` có điều kiện của ticket 13, 14 chỉ lấy ở tenant `active`, `locked`. Nên lần kích hoạt
(`platform.complete_tenant_setup()` khi chủ thứ hai thành `active`, hay `UPDATE platform.tenants SET status = 'active'` qua
`platform.guard_tenant_setup()`) đếm một chủ mà lần đình chỉ hay lần gỡ chưa commit sắp làm mất, và tenant thành `active`
với một chủ; ba bên (kích hoạt O2, đình chỉ O1, đình chỉ O2) để tenant `active` với 0 chủ (MEDIUM ngoài phạm vi ghi ở
Comments của ticket 13). Ticket này cho mọi lần mất chủ ở tenant `setup` lấy cùng khóa dòng tenant như ở tenant `active`,
và cho lối mở bằng `UPDATE` khóa dòng tenant như `complete_tenant_setup`, nên lần kích hoạt đếm sau khi lần mất commit,
hay lần mất chờ lần kích hoạt rồi được xét theo R6.7.

## Việc cần làm

Đọc ở `7ad25717` (6/11/2026):

- Chủ của R3.10: `platform.complete_tenant_setup()` (`db/migrations/versions/b5677d345bc1_tenant_roles.py:826-874`),
  AFTER `UPDATE OF status` trên `tenant_members` khi thành `active` và AFTER `INSERT OR UPDATE OF role_id, membership_id`
  trên `role_assignments` (`b5677d345bc1_tenant_roles.py:1169-1175`): khi tenant `setup`, khóa dòng tenant `FOR UPDATE`
  (`b5677d345bc1_tenant_roles.py:853`), đếm `platform.active_tenant_owners` ở câu sau (ảnh chụp mới, READ COMMITTED), đủ
  hai thì `UPDATE platform.tenants SET status = 'active'`. `platform.guard_tenant_setup()`
  (`b5677d345bc1_tenant_roles.py:801-822`), BEFORE `UPDATE OF status` trên `tenants`
  (`b5677d345bc1_tenant_roles.py:1167-1168`), từ chối `setup` → `active` khi đếm dưới hai, với 23514
  `ck_tenants_status_transition`; lệnh UPDATE đã khóa dòng tenant (`FOR NO KEY UPDATE`, `status` không trong khóa nào)
  trước khi trigger BEFORE chạy, và câu đếm của trigger lấy ảnh chụp mới. Hai hàm đếm sau khóa; không ticket nào sửa
  chúng. Lỗ chính ở phía mất chủ: không lần mất chủ nào ở tenant `setup` lấy khóa xung đột với hai khóa đó; và khóa
  `FOR NO KEY UPDATE` của lối `UPDATE` không xung đột với `FOR KEY SHARE` (gạch `guard_tenant_setup` của bước 1).
- `platform.refuse_losing_the_last_owner()`: thân mới nhất khi ticket này dựng là revision của ticket 14 (tìm bằng
  `grep -l "refuse_losing_the_last_owner" db/migrations/versions/*.py`, mới nhất theo chuỗi `down_revision`). Ba chỗ
  quyết định tenant nào được xét, mỗi chỗ có vế `status IN ('active', 'locked')`:
    - V1: câu `PERFORM ... FOR KEY SHARE` của nhánh `tenant_members` khi người chưa là chủ (bước 1 của ticket 13);
    - V2: câu `PERFORM ... FOR KEY SHARE` của phần chung khi người giữ chưa `active` (bước 1 (b) của ticket 14);
    - V3: câu trả sớm đầu của phần chung (tenant không `active`, `locked` thì `RETURN NULL`, bước 1 (b) của ticket 14),
      rồi `PERFORM 1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;` và câu đếm.
      `platform.remove_owner_assignments_first()` sau ticket 14 khóa các membership của P, không tùy trạng thái tenant, nên
      lần xóa dòng công ty ở tenant `setup` đã chờ mọi lần trao đang mở (K2 (c) là ca hồi quy của nó, không đổi ở đây).
- Thứ tự khóa: lần kích hoạt qua `complete_tenant_setup`: dòng của chính lệnh, (khóa ngoại và guard của ticket 12), dòng
  tenant `FOR UPDATE`, dòng version (trigger `trg_z_bump_access_version` của bảng, và của `tenants` khi UPDATE trạng
  thái); qua `UPDATE platform.tenants`: dòng tenant, dòng version. `check_owner_coverage` của trigger hoãn ticket 08 trả
  trước khi ghi khi tenant không `active` (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1048-1051`),
  nên ở tenant `setup` lúc commit nó không ghi `platform.tenants`; giao dịch vừa kích hoạt đã giữ dòng tenant.
- R3.14: ở tenant `setup` mọi route của công ty bị từ chối trừ lần đăng nhập đầu và lần nhận lời mời của hai chủ, và các
  route của người vận hành dưới `/api/v1/platform/` vẫn mở; lần
  kích hoạt thật là `platform.activate_invited_members` lúc đăng nhập
  (`db/migrations/versions/349080a62e41_tenant_members.py:159`, `dw_app`). Lần mất chủ ở tenant `setup` là SQL của người
  vận hành.
- Mẫu test: R3.10 ở `packages/python/dw_platform/tests/integration/test_tenant_roles.py:680-815` (`_setup_tenant`,
  `_activate`, `test_two_owners_activated_at_once_still_open_the_tenant`); harness cuộc đua và bộ đếm `40P01` ở
  `packages/python/dw_platform/src/dw_platform/testing/races.py` (bước 2 của ticket 14); hàm gieo
  `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`.

Việc:

1. **Migration**: một revision (id hex của `alembic revision`, `down_revision` là head lúc commit, sau revision của
   ticket 14). Thân `refuse_losing_the_last_owner` nạp từ revision của ticket 14, thân `guard_tenant_setup` từ
   `b5677d345bc1`, bằng `_earlier()` và sửa bằng `_patched()` (neo khớp đúng số lần
   nêu dưới, `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100`), `CREATE OR REPLACE`,
   không chép tay.
    - `platform.refuse_losing_the_last_owner()`:
        - V1, V2: hai câu `PERFORM 1 FROM platform.tenants WHERE id = v_tenant AND status IN ('active', 'locked') FOR KEY
SHARE;` (mỗi câu trải hai dòng, thụt lề như thân của 13 và 14), mỗi câu một neo riêng gồm cả dòng đứng ngay trước nó
          để khớp đúng một lần, `_patched` như đã có (không viết helper thay nhiều lần); vế thành `status IN ('setup',
'active', 'locked')`.
        - V3, theo thứ tự này: trước, câu trả sớm đầu của phần chung (neo từ `IF v_user IS NULL OR NOT EXISTS (` tới
          `t.status IN ('active', 'locked')`, khớp đúng một lần) đổi vế thành `t.status IN ('setup', 'active', 'locked')`;
          sau, câu `PERFORM 1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;` (khớp đúng một lần) thành:

            ```sql
            PERFORM 1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;
            IF NOT EXISTS (
                SELECT 1 FROM platform.tenants t
                WHERE t.id = v_tenant AND t.status IN ('active', 'locked')
            ) THEN
                RETURN NULL;
            END IF;
            ```

    - `platform.guard_tenant_setup()` (phần tử của `_SETUP` chứa `guard_tenant_setup()`, chọn theo tên không theo chỉ
      số): ngay sau dòng `IF NEW.status IS DISTINCT FROM OLD.status THEN` (neo khớp đúng một lần) chèn:

        ```sql
        IF OLD.status = 'setup' AND NEW.status = 'active' THEN
            PERFORM 1 FROM platform.tenants WHERE id = NEW.id FOR UPDATE;
        END IF;
        ```

        Câu đếm ở vế thứ ba của `IF` sau đó chạy sau khóa; không tách `IF`.

    Vì sao từng phần:
    - Lần mất chủ ở tenant `setup` (đình chỉ chủ, gỡ lần gán chủ của người `active`, đổi người của membership chủ, và lần
      gỡ lần gán do xóa dòng công ty) nay giữ dòng tenant `FOR UPDATE` tới commit. Khóa đó xung đột với `FOR UPDATE` của
      `complete_tenant_setup` và với `FOR NO KEY UPDATE` của `UPDATE platform.tenants`, nên lần kích hoạt mở sau chờ nó
      commit rồi đếm không có chủ đã mất. Vì mọi lần kích hoạt nay lấy `FOR UPDATE`, ở tenant `setup` một khóa
      chia sẻ cũng đủ chặn; câu khóa của V3 vẫn `FOR UPDATE` cho mọi trạng thái, vì sau lần chờ tenant có thể đã `active`
      và hai lần mất chủ phải xếp hàng như ở tenant `active` thay vì cùng nâng (`40P01`). Chế độ đó đã có ca của ticket
      13 (K3) và `test_two_removals_of_the_last_two_owners_queue_and_one_is_refused`; không đột biến riêng ở đây.
    - Câu đọc lại sau khóa: lần mất chủ chờ một lần kích hoạt đang mở thì sau lần chờ tenant đã `active`, nên phải được
      đếm theo R6.7 (K3); tenant còn `setup` thì không đếm, vì R3.10 xét lúc kích hoạt và tenant `setup` được mất chủ
      cuối (K4 (ii), RB20 không áp cho `setup`). Câu đọc lại cũng đúng cho tenant chuyển `active` ↔ `locked` hay sang
      `offboarding` trong lúc chờ.
    - V1, V2 ở tenant `setup`: lần mất của người mà lần kích hoạt đang mở vừa làm thành chủ (gán `tenant_owner`, kích
      hoạt lại) chỉ thấy người đó chưa là chủ, hay chưa `active`, trong ảnh chụp đầu. `FOR KEY SHARE` xung đột với
      `FOR UPDATE` mà `complete_tenant_setup` luôn lấy ở tenant `setup` trước khi đếm (cả khi chưa đủ hai), nên lần mất
      chờ lần gán hay lần kích hoạt đó, đọc lại, rồi qua V3; ngược lại, lần kích hoạt chờ lần mất đang giữ `FOR KEY SHARE`.
      Lần làm người thành chủ không qua `complete_tenant_setup` duy nhất là lần đổi người của ticket 12, mà ở tenant
      `setup` là một lần mất của người cũ: giữ `FOR UPDATE` qua V3 khi người cũ `active`, chỉ `FOR KEY SHARE` qua V2 khi
      người cũ chưa `active` (cách gieo K1 (c)). Lối sau giữ dòng tenant chỉ `FOR KEY SHARE`, nên một giao dịch đổi người
      rồi `UPDATE platform.tenants SET status = 'active'` (lối mở thứ hai) không giữ khóa nào xung đột với `FOR KEY SHARE`
      của V1, V2: lần mất người mới đọc thấy người đó chưa là chủ, trả không chờ, và lần UPDATE đếm người đó (K1 (d)).
      Nên `guard_tenant_setup` đổi một chỗ (gạch cuối). Câu của ticket 13 đã chọn vế không có `setup`
      để không chờ `complete_tenant_setup`; ở đây chờ đó là điều cần (quyết định ở Comments).
    - `complete_tenant_setup` không đổi: nó luôn khóa dòng tenant `FOR UPDATE` trước khi đếm. `guard_tenant_setup`: câu
      khóa nâng khóa `FOR NO KEY UPDATE` của chính lệnh UPDATE lên `FOR UPDATE` (đã giữ thì không chờ, như lần UPDATE của
      `complete_tenant_setup`), nên lối mở thứ hai xung đột với `FOR KEY SHARE` như lối thứ nhất. Chỉ ở lần chuyển
      `setup` → `active`: lần UPDATE trạng thái khác không khóa thêm.

    Thứ tự khóa của lần mất chủ ở tenant `setup`: dòng của chính lệnh, dòng tenant (`FOR KEY SHARE` hay `FOR UPDATE`),
    dòng version: cùng thứ tự "dòng tenant trước dòng version" của lần kích hoạt. Chi phí có chủ ý: trong khi một lần mất
    chủ ở tenant `setup` còn mở, mọi INSERT có khóa ngoại tới tenant đó chờ (`FOR UPDATE`); tenant `setup` không nhận
    route nào của công ty ngoài lần đăng nhập đầu và lần nhận lời mời (R3.14), chỉ các route người vận hành dưới
    `/api/v1/platform/` (như `org-admins`, gán `tenant_owner` qua `complete_tenant_setup`, nên cũng chờ); lần đăng nhập của
    một chủ được mời chờ lần mất chủ đó commit, và vì `activate_invited_members` đổi mọi dòng `invited` của người đó ở mọi
    tenant trong một lệnh ở đầu giao dịch đăng nhập (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:117-122`),
    lần đăng nhập đó chờ ở mọi công ty, không chỉ tenant ấy (thời hạn chờ là việc của runbook vận hành, Comments). Dạng `40P01` mới, mọi dạng đều đóng (một bên bị hủy, không bên nào lọt):
    - giao dịch nhiều câu ở tenant `setup` đã giữ dòng version từ một câu trước rồi lấy dòng tenant `FOR UPDATE` (lần gán
      `tenant_owner` sau, qua `complete_tenant_setup`), xen giữa là một lần mất chủ ở cùng tenant đang giữ dòng tenant rồi
      chờ dòng version; hôm nay lần mất chủ không khóa dòng tenant nên không có vòng;
    - ca của K1 (d): giao dịch đổi người (các câu đầu giữ dòng version) rồi `UPDATE platform.tenants` (câu sau chờ ở
      `FOR UPDATE` của `guard_tenant_setup`), xen giữa là các lần đình chỉ người mới giữ `FOR KEY SHARE` rồi chờ dòng
      version: một hay hai bên bị hủy; hôm nay mọi bên được nhận và tenant `active` với 0 chủ;
    - hai lần mất của hai người cùng được làm thành chủ bởi một lần kích hoạt đang mở (V1, V2 cùng giữ `FOR KEY SHARE`
      rồi cùng nâng). "Không `40P01`" của tiêu chí là cho lệnh một dòng như các ca của K.

    Không bảng, cột, quyền vai, hàm mới, trigger mới hay route, nên `test_rls_coverage.py`, `test_privileges.py` và
    `test_offboarding_coverage.py` không đổi và phải xanh (tenant `setup` sang `offboarding` vẫn qua `guard_tenant_setup`,
    không khóa thêm; lần xóa của offboarding ở tenant `offboarding`, ngoài vế). Downgrade dựng lại thân của ticket 14 và thân
    `guard_tenant_setup` của `b5677d345bc1` (từ chính các module `_earlier`, qua `CREATE OR REPLACE`).

2. **Test** (integration, tệp mới `packages/python/dw_platform/tests/integration/test_setup_activation_races.py`, dùng
   harness của `dw_platform.testing.races`; không sửa `test_tenant_roles.py` hay tệp test của ticket 13, 14): mỗi ca trên
   tenant `setup` gieo mới dưới `dw_migrator` như `_setup_tenant` của `test_tenant_roles.py` (chủ được mời, kích hoạt bằng
   `UPDATE platform.tenant_members SET status = 'active'` như `_activate`); mọi bên dưới `dw_migrator`. Ca "bên mất chủ
   trước" theo dạng `_race`: bên mất chủ giữ giao dịch mở, lần kích hoạt chạy trong một task tới khi chờ khóa hay đã
   xong, bên mất chủ commit. Harness đếm SQLSTATE `40P01`, phải là 0 ở mọi ca trừ K1 (d); ở K1 (d) bắt `DBAPIError` ở câu cuối của A, ở lần commit
   của A và ở task của B, C. Sau mỗi ca: khi tenant `active`, nó có ít
   nhất một chủ `active`; khi tenant được mở qua `complete_tenant_setup` thì có đúng một sự kiện audit
   `platform.tenant.setup_completed`, `owner_ids` của nó bằng đúng tập hai chủ mà ca dự tính (so với tập đó, không với
   chủ hiện tại); khi tenant còn `setup`, không sự kiện nào. Lối `UPDATE platform.tenants` (K1 (c)) không ghi audit: không
   khẳng định audit ở đó.
3. `reviewing-feature-security` (ranh giới 1, 2, 6; 3 và 5 không áp như ticket 14), `mutations/15.yaml` một đột biến mỗi
   dòng ở cột "Đột biến" dưới đây, không chạy `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng tay. Độ
   trễ: các câu khóa thêm chỉ chạy khi mất chủ ở tenant `setup`, việc của người vận hành; câu khóa của
   `guard_tenant_setup` chỉ ở lần chuyển `setup` → `active`, khóa đã giữ. Câu đọc lại sau `FOR UPDATE` của V3 chạy ở mọi
   lần mất chủ ở tenant `active`, `locked`, trong đó có route gỡ lần gán dưới `dw_app`
   (`packages/python/dw_platform/src/dw_platform/adapters/persistence/role_assignments_repo.py:328`) khi gỡ
   `tenant_owner`: một câu đọc theo khóa chính; đo P50/P95/P99 của route đó với lần gán `tenant_owner` ở lúc đóng hàng
   đợi (`.claude/rules/latency.md`).

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                                                   | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Đột biến (`mutations/15.yaml`)                                                                                                                                                                                                 |
| --- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| K1  | Lần kích hoạt cạnh lần mất một chủ đã có không mở công ty với một chủ       | Tenant `setup`, O1 là chủ `active`, O2 là chủ `invited`. Bên mất chủ trước, giữ mở; lần kích hoạt O2 chạy tới khi chờ khóa; bên mất chủ commit → lần kích hoạt nhận, tenant còn `setup`, không sự kiện `setup_completed`: (a) đình chỉ O1; (b) gỡ lần gán `tenant_owner` của O1. (c) Tenant `setup` có hai chủ `active` mà chưa mở (gieo: O1 `active`, rồi `dw_migrator` đổi membership chủ của O2 `invited` sang Y `active`, Y chưa có membership ở workspace đó, lối không qua `complete_tenant_setup`): đình chỉ O1 trước, giữ mở; `UPDATE platform.tenants SET status = 'active'` chạy tới khi chờ khóa; commit → UPDATE bị từ chối với 23514 `ck_tenants_status_transition`, tenant còn `setup`. (d) Lối đổi người rồi UPDATE, ba bên: tenant `setup` không có chủ `active`, O2 và O3 `invited` giữ `tenant_owner` qua M2, M3; P1, P2 `active` chưa có membership ở workspace đó; bên A một giao dịch ba câu dưới `dw_migrator`: đổi M2 sang P1, đổi M3 sang P2, rồi `UPDATE platform.tenants SET status = 'active'`; A chạy hai câu đầu; bên B đình chỉ P1 và bên C đình chỉ P2, mỗi bên chạy tới khi chờ khóa (dòng version); A câu 3 chạy trong một task, harness chờ task đó kết thúc (xong, hay bị hủy khi bộ dò khóa chết chọn A), commit A nếu còn sống, rồi chờ B, C kết thúc và commit bên còn sống → ít nhất một bên bị hủy với `40P01`; tenant `active` thì P1, P2 đều là chủ `active`, không thì tenant còn `setup` (dưới đột biến (c) và ở commit gốc A câu 3 không chờ, đếm P1, P2 khi hai lần đình chỉ chưa commit, cả ba bên nhận: tenant `active` với 0 chủ). Đối chứng, thứ tự ngược của (a): lần kích hoạt O2 trước, đình chỉ O1 chờ rồi được xét theo R6.7 → cả hai nhận, tenant `active` với đúng một chủ `active` (O2) | (a) bỏ `'setup'` khỏi câu trả sớm đầu của V3 ((a), (b), (c) đỏ: tenant `active` với một chủ); (c) bỏ câu `PERFORM ... FOR UPDATE` của `guard_tenant_setup` ((d) đỏ). Không có đột biến (b): chế độ khóa của V3 thuộc ticket 13 |
| K2  | Lần kích hoạt cạnh lần mất người vừa thành chủ không mở công ty với một chủ | Tenant `setup`, O1 là chủ `active`. Bên mất trước, giữ mở; lần ghi kích hoạt chạy tới khi chờ khóa; bên mất commit → tenant còn `setup`: (a) P `active` không phải chủ; đình chỉ P, rồi gán `tenant_owner` lên membership của P (V1). (b) Q giữ `tenant_owner` và `suspended` (gieo dòng công ty của Q `suspended` trước khi gán, không qua `active`, để tenant không mở lúc gieo); gỡ lần gán `tenant_owner` của Q, rồi kích hoạt lại Q (V2). (c) Ca hồi quy cho khóa membership của ticket 14 ở tenant `setup`: P `active` không phải chủ có membership M_P; bên A một giao dịch hai câu: gán `tenant_owner` lên M_P (mở công ty), rồi đình chỉ O1 (A đếm P, nhận), giữ mở; bên B xóa dòng công ty của P chạy tới khi chờ khóa; A commit → B bị từ chối với 23514 `ck_role_assignments_last_owner`, tenant `active` với P là chủ `active`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | (a) bỏ `'setup'` khỏi V1 ((a) đỏ); (b) bỏ `'setup'` khỏi V2 ((b) đỏ); (c) là ca hồi quy, đột biến của nó là K1 (a) của ticket 14                                                                                               |
| K3  | Lần mất chủ chờ lần kích hoạt được đếm theo R6.7, kể cả ba bên              | (i) Hai bên, tất định: tenant `setup`, O1 là chủ `active`, O2 là chủ `invited`; bên A một giao dịch hai câu: kích hoạt O2 (tenant `active`), rồi đình chỉ O2 (A đếm O1, nhận), giữ mở; bên B đình chỉ O1 chạy tới khi chờ ở dòng tenant; A commit → B bị từ chối với 23514 `ck_role_assignments_last_owner`, tenant `active` với O1 là chủ `active`. (ii) Ba bên: cùng gieo; bên A kích hoạt O2 và giữ mở (tenant `active` khi A commit); bên B đình chỉ O1 và bên C đình chỉ O2, mỗi bên chạy tới khi chờ khóa (B ở dòng tenant, C ở dòng công ty của O2); A commit → đúng một trong B, C bị từ chối với 23514 `ck_role_assignments_last_owner`, bên kia nhận, không `40P01`, tenant `active` với đúng một chủ `active`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | (a) đặt câu đọc lại của V3 trước câu `FOR UPDATE` (trả theo trạng thái đọc trước khóa) ((i) đỏ: B không được đếm, tenant `active` với 0 chủ; (ii) chỉ đỏ khi C tới dòng tenant trước B, không dùng làm bằng chứng)             |
| K4  | Khóa thêm không đổi luồng `setup` thường                                    | (i) Hai lần kích hoạt đồng thời vẫn xếp hàng và mở công ty (`test_two_owners_activated_at_once_still_open_the_tenant` xanh, không sửa). (ii) Tenant `setup` có O1 là chủ `active` duy nhất và O2 `invited`, không lần kích hoạt nào mở: đình chỉ O1 → nhận, tenant còn `setup` (tenant `setup` được mất chủ cuối); gỡ lần gán `tenant_owner` của O2 → nhận                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | (a) câu đọc lại của V3 dùng `status IN ('setup', 'active', 'locked')` (đếm cả tenant `setup`; (ii) đỏ: lần đình chỉ bị từ chối)                                                                                                |

## Tiêu chí chấp nhận

- [x] R3.10 (RB38): K1, lần mất chủ O1 (đình chỉ, gỡ lần gán) đang mở rồi lần kích hoạt O2 cho tenant còn `setup` sau khi
      cả hai commit, và lần `UPDATE platform.tenants SET status = 'active'` cạnh lần đình chỉ O1 đang mở bị từ chối với
      23514 `ck_tenants_status_transition`; thứ tự ngược nhận cả hai và để tenant `active` với một chủ; không `40P01`; sai
      nếu tenant `active` sau một ca "bên mất chủ trước", ca đối chứng bị từ chối, hay đột biến (a) của K1 vẫn xanh; K1
      (d) cho ít nhất một bên bị hủy với `40P01` và tenant `active` chỉ khi P1, P2 đều là chủ `active`, sai nếu đột biến
      (c) của K1 vẫn xanh. Ở commit gốc (sau ticket 14) (a), (b), (c) để tenant `active` với một chủ `active`, và (d) nhận
      mọi bên với 0 chủ.
- [x] R3.10 (RB38): K2 (a), (b), lần mất người mà lần kích hoạt sắp làm thành chủ, đang mở trước lần kích hoạt, cho tenant
      còn `setup`; sai nếu tenant `active`, hay đột biến (a), (b) của K2 vẫn xanh. Ở commit gốc hai ca đó để tenant
      `active` với một chủ `active`.
- [x] R6.7 (RB20): K3 (i), lần đình chỉ O1 chờ giao dịch đã kích hoạt rồi đình chỉ O2 bị từ chối với 23514
      `ck_role_assignments_last_owner` sau khi giao dịch đó commit, tenant `active` với O1; sai nếu B được nhận, hay đột
      biến của K3 vẫn xanh. Ở commit gốc B được nhận và tenant `active` với 0 chủ `active`.
- [x] R6.7 (RB20): K2 (c), lần xóa dòng công ty của P chờ giao dịch đã gán chủ cho P (mở công ty) rồi đình chỉ O1 bị từ
      chối với 23514 `ck_role_assignments_last_owner`, tenant `active` với P; sai nếu B được nhận. Ca hồi quy: đã đúng
      sau ticket 14.
- [x] R6.7 (RB20): K3 (ii), ba bên quanh một lần kích hoạt đang mở cho đúng một lần đình chỉ bị từ chối với 23514
      `ck_role_assignments_last_owner` và tenant `active` với đúng một chủ `active`, không `40P01`; sai nếu tenant `active`
      với 0 chủ hay một bên `40P01`. Ở commit gốc ca này để tenant `active` với 0 chủ khi C đếm trước khi B commit (cuộc
      đua, nên không là bằng chứng đỏ; bằng chứng là K3 (i)).
- [x] R3.10 (RB38): K4, hai lần kích hoạt đồng thời vẫn mở công ty, và ở tenant `setup` không có lần kích hoạt mở lần
      đình chỉ chủ `active` duy nhất và lần gỡ lần gán chủ được mời được nhận, tenant còn `setup`; sai nếu một trong các
      ca đó bị từ chối, hay đột biến của K4 vẫn xanh.
- [x] Xong: `uv run python -m pytest packages/python/dw_platform/tests/integration/test_setup_activation_races.py packages/python/dw_platform/tests/integration/test_tenant_roles.py packages/python/dw_platform/tests/integration/test_owner_count_races.py packages/python/dw_platform/tests/integration/test_last_owner_races.py packages/python/dw_platform/tests/integration/test_role_administration_db.py packages/python/dw_platform/tests/integration/test_membership_change_of_person.py packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py` xanh.

## Nguồn

- `db/migrations/versions/b5677d345bc1_tenant_roles.py:801-822`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:826-874`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:853`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:1167-1175` (R3.10, R3.15); `db/migrations/versions/349080a62e41_tenant_members.py:159` (`activate_invited_members`).
- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:870-932` (R6.7), `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:938-957` (`remove_owner_assignments_first`), `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1048-1051` (`check_owner_coverage` chỉ cho tenant `active`); bước 1 của ticket 13 và 14.
- `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100` (`_earlier`, `_patched`).
- `packages/python/dw_platform/tests/integration/test_tenant_roles.py:680-815`, `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`.
- Spec: R3.10, R3.14, R6.7, RB20, RB38; ADR-0104 (Accepted) mục 6, mục 10 (`setup`), Amendments 2026-10-25, 2026-10-26; Comments của ticket 13 ("Ngoài ticket, có chủ ý").

## Comments

- 2026-11-06 (agent, theo ủy quyền 31/10/2026): cắt từ mục "Ngoài ticket, có chủ ý" ở Comments của ticket 13. Đã dựng
  lại trên code ở `7ad25717` cộng thân của ticket 12, 13, 14 như đặc tả: lỗ thật ở thứ tự "bên mất chủ trước" (lần kích
  hoạt đếm chủ mà lần mất chưa commit, rồi chỉ chờ ở dòng version khi đã đổi trạng thái), và ở ba bên cho 0 chủ; thứ tự
  "kích hoạt trước" cho đúng kết quả nối tiếp (lần mất được xét sau, ở tenant đã `active`, trừ khi một bên thứ ba cùng
  mất). Chọn sửa phía mất chủ thay vì cho lần kích hoạt khóa các dòng chủ nó đếm (`FOR SHARE` trên lần gán, membership,
  dòng công ty): cách đó chép lại định nghĩa của `platform.active_tenant_owners` vào câu khóa (failure-modes #2), không
  khóa được người vừa thành chủ qua lần đổi người, và để tenant kẹt ở `setup` khi đếm thiếu; phía mất chủ dùng cùng một
  điểm xếp hàng (dòng tenant) mà mọi lần xét chủ đã dùng. Nếu sai thì: `complete_tenant_setup` và `guard_tenant_setup`
  đếm qua một câu khóa `FOR SHARE OF a, m, tm` và V1-V4 về như ticket 14.
  Không gộp vào ticket 14 dù cùng hai hàm: khác yêu cầu (R3.10 ở tenant `setup` so với R6.7 ở `active`, `locked`), khác
  bộ kiểm soát (lần kích hoạt, hai đường kích hoạt, ba bên), và 14 đã đủ bốn kiểm soát; ticket này chỉ đổi vế trạng thái
  của các câu 13, 14 viết, thêm một câu đọc lại. `Blocked by: 14` vì cùng thay thân hai hàm bằng `CREATE OR REPLACE`
  (V2, V4 chỉ có sau 14) và dùng harness 14 đưa vào `dw_platform.testing.races`. Đảo quyết định của ticket 13 (vế không
  có `setup` để không chờ `complete_tenant_setup`): chờ đó chính là điều đóng lỗ. Nếu sai thì: gộp bước 1 vào revision
  của ticket 14 và K1-K4 thành kiểm soát của 14, gate lại 14.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk một
  subagent, ranh giới 1, 2, 6; 3, 5 không áp). Một HIGH, sửa ở ticket: (1) đột biến bỏ câu đọc lại của V3 không chết được
  bằng ca ba bên cũ của K3, vì sau lần commit của A bên B (chờ thẳng ở dòng tenant) hầu như luôn tới trước C, nên dưới đột
  biến kết quả vẫn "đúng một bên bị từ chối": thêm K3 (i) hai bên tất định (A kích hoạt O2 rồi đình chỉ O2, B đình chỉ O1
  chờ, A commit → B 23514), đột biến chỉ nhận ở (i); ca ba bên thành K3 (ii), không làm bằng chứng đỏ. Cùng lý do, K2 (c)
  ba bên đổi thành hai bên tất định (A gán chủ cho P rồi đình chỉ O1, B xóa dòng công ty của P). MEDIUM, sửa: (2) neo của
  V1, V2: `_patched` chỉ nhận neo khớp đúng một lần, nên mỗi câu một neo riêng kèm dòng trước nó, không helper thay nhiều
  lần; (3) V3 sửa câu trả sớm trước rồi mới chèn câu đọc lại, để neo không khớp hai lần; (4) V4 nay là hai câu (ticket 14
  thêm nhánh `FOR UPDATE` khi P đã là chủ), cả hai thêm `setup`. LOW, sửa: (5) lần đổi người có người cũ chưa `active`
  qua V2, không V3, và vì sao vẫn đóng; (6) audit `setup_completed` chỉ có ở lối `complete_tenant_setup`, so `owner_ids`
  với tập dự tính; (7) R3.14 còn mở các route người vận hành dưới `/api/v1/platform/` (`org-admins`), cũng chờ.
  MEDIUM, không sửa, người dựng đọc trước: (a) không ca nào chạy lần kích hoạt thật, `platform.activate_invited_members`
  dưới `dw_app`, cạnh một lần mất chủ đang mở; cùng trigger nên rủi ro thấp, người dựng thêm được một biến thể K1 (a).
  (b) Câu `FOR UPDATE` của V4 (P đã là chủ, tenant `setup`) không có ca riêng: bỏ `setup` ở đó mọi K vẫn xanh, vì nhánh
  `role_assignments` sau đó cũng qua V3; nó chỉ cần cho P có hai membership mang chủ, như K1 (iii) của ticket 14. (c) Lần
  mất chủ đang mở ở tenant B không chặn lần kích hoạt ở tenant A: không ca riêng, như (c) lượt đầu gate 13. (d) Lối
  `UPDATE platform.tenants SET status = 'active'` mở công ty không ghi audit nào: có từ trước, no owner yet (chủ là R3.10,
  `guard_tenant_setup`, hay script người vận hành). (e) V3 trả `RETURN NULL` cho mọi trạng thái ngoài `active`, `locked`:
  một trạng thái thêm sau này mặc định không xét (failure-modes #7); hôm nay `ck_tenants_status` cố định tập. (f) Lệnh
  nhiều dòng đình chỉ mọi chủ của tenant `setup` cạnh lần kích hoạt: đóng, có thể `40P01`; tiêu chí cho lệnh một dòng.
  Sửa sau lượt này được lượt xác nhận đọc lại.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới, builder check và boundary walk một
  subagent). Một HIGH, sửa ở ticket: (1) lối mở thứ hai (`UPDATE platform.tenants`, lấy `FOR NO KEY UPDATE`) không xung
  đột với `FOR KEY SHARE` của V1, V2, V4, nên giao dịch `dw_migrator` đổi membership chủ của O2 `invited` sang P `active`
  rồi mở công ty (lối 12 để mở, vì lần đổi người không mở công ty) đếm P trong khi lần đình chỉ P (thấy P chưa là chủ) trả
  không chờ; bên thứ ba đình chỉ O1 cho 0 chủ. Nay `guard_tenant_setup` khóa dòng tenant `FOR UPDATE` trước câu đếm ở lần
  chuyển `setup` → `active`, K1 (d) và đột biến K1 (c), dạng `40P01` của ca đó nêu ở danh sách; câu "không đổi
  `guard_tenant_setup`" bỏ. Phương án của người đọc (V1, V2, V4 dùng `FOR SHARE` ở tenant `setup`) không chọn: nó đổi bốn
  câu thay vì một, và hai lần mất cùng chờ một lần kích hoạt thì cùng nâng (`40P01`). Nếu sai thì: V1, V2, V4 `FOR SHARE`
  khi tenant `setup`, `guard_tenant_setup` không đổi. MEDIUM, sửa: (2) đột biến K3 ghi rõ "câu đọc lại đặt trước câu
  khóa" (xóa hẳn câu đọc lại thì chỉ K4 (ii) đỏ). LOW, sửa: (3) câu đọc lại của V3 chạy ở route gỡ lần gán `tenant_owner`
  dưới `dw_app`: đo ở lúc đóng hàng đợi; (4) K2 (b) gieo Q `suspended` thẳng, không qua `active`. Không sửa, người dựng
  đọc trước: (a) giao dịch mất chủ của người vận hành bỏ mở ở tenant `setup` giữ dòng tenant vô hạn, chặn lần đăng nhập
  đầu: no owner yet (runbook, `idle_in_transaction_session_timeout` cho `dw_migrator`). (b) Không ca hai tenant (lần mất
  ở B không chặn lần kích hoạt ở A), như (c) lượt đầu. Sửa sau lượt này không được người đọc mới đọc lại; người dựng đọc
  bước 1 (gạch `guard_tenant_setup`) và K1 (d) trước.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận thứ hai (người đọc mới). Một HIGH, sửa ở ticket: (1) K1
  (d) cũ không chạy được: bên C đình chỉ O1 (chủ trong ảnh chụp của C) đi thẳng tới `FOR UPDATE` của V3, xung đột với
  `FOR KEY SHARE` mà B giữ, nên C chỉ đếm sau khi B commit và harness "chờ C xong rồi mới commit B" treo; còn hai bên A, B
  cho đúng kết quả nối tiếp A;B. Nay K1 (d) là ca ba bên tất định: A đổi M2, M3 của hai chủ được mời sang P1, P2 rồi
  `UPDATE` trạng thái, B và C đình chỉ P1, P2 (cả hai giữ `FOR KEY SHARE` qua V1); dưới đột biến và ở commit gốc tenant
  `active` với 0 chủ. MEDIUM, sửa: (2) đột biến K1 (b) (`FOR KEY SHARE` ở V3) không chết từ khi `guard_tenant_setup` khóa
  `FOR UPDATE`: bỏ, chế độ khóa của V3 thuộc ticket 13 và có ca ở đó; câu "Vì sao" sửa theo; (3) bộ đếm `40P01` của
  harness: K1 (d) là ngoại lệ, nêu chỗ bắt `DBAPIError`; (4) dòng Quyết định của spec nói `guard_tenant_setup` không đổi:
  sửa cùng lượt này; (5) lần đăng nhập chờ ở mọi công ty (lệnh nhiều tenant của `activate_invited_members`), nêu ở phần
  chi phí. LOW, sửa: (6) neo của `guard_tenant_setup` và văn bản chèn; (7) Y chưa có membership ở workspace của M (K1
  (c)). Ticket 14 lượt này đổi (a) sang khóa các membership của P, không tùy trạng thái tenant, nên V4 bỏ khỏi ticket
  này; K2 (c) thành ca hồi quy của ticket 14. Sửa sau lượt này không được người đọc mới đọc lại (hai lượt chạy lại mỗi
  phiên bản đã dùng); người dựng đọc bước 1 (gạch `guard_tenant_setup`) và K1 (d) trước.
- 2026-11-06 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): dựng xong, `resolved`. Revision `cae9cc86159c` (trên `a6b8f3702570`):
  thân `refuse_losing_the_last_owner()` của ticket 14 sửa bốn neo bằng `_patched()` (V1, V2, câu trả sớm đầu của V3 thêm
  `setup`; câu đọc lại trạng thái tenant sau `FOR UPDATE`), `guard_tenant_setup()` từ phần tử của `_SETUP` của
  `b5677d345bc1` (chọn theo tên) thêm `FOR UPDATE` ở lần `setup` → `active`; downgrade dựng lại hai thân. Test:
  `packages/python/dw_platform/tests/integration/test_setup_activation_races.py`, 12 ca, harness của
  `dw_platform.testing.races`. Khác ticket, theo số đo: K2 (b) (gỡ lần gán chủ của Q `suspended` trước lần kích hoạt lại
  Q) đã đóng ở chỗ khác: lệnh UPDATE `tenant_members` của lần kích hoạt lại chờ một dòng mà giao dịch gỡ đang giữ (đo bằng
  `pg_locks`: `transactionid` `ShareLock`) trước khi `complete_tenant_setup` đếm, nên dưới đột biến K2 (b) (bỏ `setup` khỏi
  V2) ca đó vẫn để tenant `setup`; đột biến đó tương đương, không vào `mutations/15.yaml` (5 đột biến), đầu tệp ghi lý do;
  vế `setup` của V2 giữ như ticket ghi. Nếu sai thì: một đường kích hoạt lại không chờ dòng đó (một trigger đổi thứ tự) thì
  thêm lại đột biến (b). Gate nhanh: ruff, format, mypy, integration của dòng Xong 311 xanh. Phá thử bằng tay 5 đột biến:
  cả 5 đỏ đúng lý do (K1 (a) tenant mở với một chủ, K1 (c) không bên nào bị hủy ở K1 (d), K2 (a) tenant `active`, K3 (a)
  lần đình chỉ thứ hai được nhận, K4 (a) lần đình chỉ ở tenant `setup` bị từ chối). `reviewing-feature-security`: ranh giới
  1 (khóa đúng dòng tenant của `v_tenant`/`NEW.id`), 2 (mọi người ghi kể cả `dw_migrator`), 6 (lần mất chủ và lần mở ở
  tenant `setup` là lối cuối, test ở tầng database); 3, 5 không áp như ticket 14; 4 không áp. Độ trễ: câu đọc lại sau
  `FOR UPDATE` chạy ở mọi lần mất chủ của tenant `active`, `locked` (route gỡ lần gán `tenant_owner`), đo P50/P95/P99 lúc
  đóng hàng đợi như bước 3 ghi.
