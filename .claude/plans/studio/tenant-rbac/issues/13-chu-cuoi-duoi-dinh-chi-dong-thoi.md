# 13 — Chủ sở hữu cuối dưới lần đình chỉ người vừa thành chủ

Status: ready-for-agent
Blocked by: 12
Area: studio
Yêu cầu: R6.7, RB20

## Mục tiêu

R6.7: không thay đổi nào làm tenant `active` hay `locked` mất chủ sở hữu công ty `active` cuối. Hôm nay điều đó đúng cho
mỗi lần ghi xét một mình, và cho hai lần gỡ chủ đồng thời (cả hai khóa dòng tenant `FOR UPDATE` trước khi đếm), nhưng
không cho một lần đình chỉ người P cạnh một giao dịch làm P thành chủ rồi gỡ chủ cuối Q: nhánh `tenant_members` của
`platform.refuse_losing_the_last_owner()` thấy P chưa giữ `tenant_owner` trong ảnh chụp của nó và trả sớm, không khóa
gì; giao dịch kia đếm P còn `active` vì lần đình chỉ chưa commit. Cả hai được nhận, tenant còn 0 chủ `active`. Hai lối
có dạng đó: lần `dw_migrator` đổi membership của Q sang P mà ticket 12 xét (MEDIUM (a) của cả hai lượt gate ticket 12),
và lần trao chủ trong một giao dịch (gán `tenant_owner` cho P rồi gỡ của Q), có sẵn từ ticket 03. Ticket này cho lần
đình chỉ chờ mọi lần xét chủ cuối đang mở rồi đọc lại, mà không thêm cuộc đua `40P01` nào với trigger hoãn của ticket 08.

## Việc cần làm

Đọc ở `a53b042b` (6/11/2026):

- `platform.refuse_losing_the_last_owner()`: thân duy nhất ở
  `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:870-932`, AFTER trên
  `role_assignments` và `UPDATE OF status` trên `tenant_members`
  (`d2b57239ef50_role_administration_and_anti_escalation.py:1126-1131`). Nhánh `tenant_members`
  (`d2b57239ef50_role_administration_and_anti_escalation.py:898-910`) trả sớm khi người không giữ `tenant_owner`; phần
  chung khóa dòng tenant `FOR UPDATE` rồi đếm `platform.active_tenant_owners`
  (`d2b57239ef50_role_administration_and_anti_escalation.py:923`, hàm ở `db/migrations/versions/b5677d345bc1_tenant_roles.py:499-512`).
  Lần gỡ, đổi `role_id` hay `membership_id` của lần gán `tenant_owner` của một người `active`, lần đình chỉ một chủ, và
  nhánh `memberships` của ticket 12 lấy khóa đó trước khi đếm; lần ghi làm P thành chủ (INSERT lần gán, lần đổi người)
  không khóa gì ở hàm này. Hai lối khác làm giảm số chủ mà không khóa (lần xóa dòng công ty hay người dùng, và lần gỡ
  lần gán của một người chưa `active`) nằm ngoài ticket này, xem Comments.
- Ticket 12 thêm nhánh `ELSIF TG_TABLE_NAME = 'memberships'` trước nhánh `ELSE` và để nhánh `ELSE` nguyên văn; revision
  của nó là thân mới nhất của hàm khi ticket này dựng (tìm bằng `grep -l "refuse_losing_the_last_owner"
db/migrations/versions/*.py`, revision mới nhất theo chuỗi `down_revision`).
- `platform.tenant_members`: khóa chính `(tenant_id, user_id)`, `status` không nằm trong chỉ mục unique nào
  (`db/migrations/versions/349080a62e41_tenant_members.py:93-110`), nên lần đình chỉ khóa dòng `FOR NO KEY UPDATE`, không
  xung đột với `FOR KEY SHARE` mà khóa ngoại của lần đổi người lấy trên dòng của P.
- Ticket 08 (`db/migrations/versions/a7ca12c36ec7_owner_coverage_per_transaction_and_hold_rule_per_anchor.py`, đang
  dựng): trigger ràng buộc hoãn tới commit trên bốn bảng gọi `platform.check_owner_coverage`, hàm chỉ ghi
  `platform.tenants` (`UPDATE ... SET owner_coverage_low_since`,
  `d2b57239ef50_role_administration_and_anti_escalation.py:1066-1067`) ở lần chuyển qua ngưỡng hai người, sau khi giao
  dịch đã giữ dòng version. UPDATE không đổi khóa nên lấy `FOR NO KEY UPDATE` trên dòng tenant.
- Thứ tự khóa của ticket 12 (bước 1 của nó): dòng membership, dòng vai trò, khóa tư vấn, dòng tenant, dòng version; trigger
  AFTER theo dòng bắn theo thứ tự tên, nên trên `tenant_members` `ck_role_assignments_last_owner` (dòng tenant) bắn
  trước `trg_z_bump_access_version` (dòng version). Gate 12 ghi: `check_owner_coverage` lúc commit lấy dòng tenant sau
  dòng version, nên cạnh một lần ghi lấy dòng tenant `FOR UPDATE` rồi dòng version nó có thể cho `40P01` (đóng, không
  lọt); chủ là ticket 08.
- Không route nào đình chỉ thành viên công ty (`apps/api/src/dw_api/routes/v1/admin_members.py` không ghi `status`
  thành `suspended`); lần đình chỉ hôm nay là SQL của người vận hành.
- Mẫu test: R6.7 ở `packages/python/dw_platform/tests/integration/test_role_administration_db.py:733-850` (cả
  `test_two_removals_of_the_last_two_owners_queue_and_one_is_refused`), `plant_world` ở
  `test_role_administration_db.py:192-232`; cuộc đua hai kết nối thật `_race`, `_blocked`, `_until` ở
  `packages/python/dw_platform/tests/integration/test_service_principals_db.py:389-440`; hàm gieo
  `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`.

Việc:

1. **Migration**: một revision (id hex của `alembic revision`, `down_revision` là head lúc commit, sau revision của
   ticket 12). Thân hàm nạp từ revision của ticket 12 bằng `_earlier()` và sửa bằng `_patched()` (neo khớp đúng một lần,
   như `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100`), `CREATE OR REPLACE`, không
   chép tay. Chỉ nhánh `ELSE` (`tenant_members`) đổi; neo là câu `IF NOT EXISTS (...) THEN RETURN NULL; END IF;` của
   nhánh đó (câu có `m.user_id = v_user AND r.key = 'tenant_owner'`), thay bằng:

    ```sql
    IF NOT EXISTS (<câu của neo>) THEN
        PERFORM 1 FROM platform.tenants
        WHERE id = v_tenant AND status IN ('active', 'locked') FOR KEY SHARE;
        IF NOT EXISTS (<câu của neo>) THEN
            RETURN NULL;
        END IF;
    END IF;
    ```

    `<câu của neo>` là đúng chuỗi của neo, lấy một lần trong Python và dùng hai chỗ, không gõ lại. Vì sao từng phần:
    - Lần ghi nào sắp làm P thành chủ và gỡ chủ khác đều giữ dòng tenant `FOR UPDATE` tới commit; `FOR KEY SHARE` xung
      đột đúng với khóa đó, nên lần đình chỉ chờ nó commit. Hàm `VOLATILE` (mặc định) ở READ COMMITTED lấy ảnh chụp mới
      mỗi câu, nên câu đọc thứ hai thấy P đã là chủ, và phần chung đếm 0 rồi từ chối. Ngược lại, lần đình chỉ giữ
      `FOR KEY SHARE` tới commit, nên lần ghi kia chờ ở `FOR UPDATE` của nó rồi đếm P đã `suspended`.
    - Không `FOR UPDATE` hay `FOR NO KEY UPDATE`: hai chế độ đó xung đột với `FOR NO KEY UPDATE` của
      `check_owner_coverage` lúc commit, nên mọi lần đình chỉ (không chỉ lần đình chỉ chủ) cạnh một giao dịch ticket 08
      sắp ghi `owner_coverage_low_since` thành `40P01`: rộng thêm đúng dạng gate 12 ghi. `FOR UPDATE` còn chặn mọi lần
      INSERT có khóa ngoại tới `platform.tenants` của tenant tới khi lần đình chỉ commit. `FOR KEY SHARE` không xung đột
      với khóa ngoại, với lần đình chỉ khác, hay với UPDATE không đổi khóa.
    - Khóa chỉ lấy khi người không phải chủ trong ảnh chụp đầu: người đã là chủ đi thẳng tới `FOR UPDATE` của phần chung
      như hôm nay, vì hai lần đình chỉ hai chủ cuối cùng giữ `FOR KEY SHARE` rồi cùng nâng lên `FOR UPDATE` thì khóa chết
      (`40P01`) thay vì xếp hàng như `test_two_removals_of_the_last_two_owners_queue_and_one_is_refused`.
    - Phần chung không đổi: người vừa thành chủ sau lần chờ đi tới `FOR UPDATE` (nâng từ `FOR KEY SHARE` của chính nó).
    - Chỉ tenant `active` hay `locked` (vế `status` của câu khóa): ở tenant khác phần chung không xét, nên lần đình chỉ ở
      đó không khóa thêm gì và không chờ `FOR UPDATE` của `complete_tenant_setup` ở tenant `setup`.
    - Bảo đảm này là của READ COMMITTED, mức của mọi kết nối nền tảng; lần đếm sau `FOR UPDATE` hôm nay cũng dựa vào
      nó. Ở REPEATABLE READ câu đọc lại dùng ảnh chụp của giao dịch: ngoài ticket, như phần chung hôm nay.

    Thứ tự khóa của lần đình chỉ: dòng `tenant_members`, dòng tenant (`FOR KEY SHARE` hay `FOR UPDATE`), dòng version
    (`trg_z_bump_access_version`, mọi UPDATE trên `tenant_members` đều lấy), lúc commit dòng tenant lần nữa
    (`check_owner_coverage`, đã giữ): cùng thứ tự "dòng tenant trước dòng version" của ticket 12. Dạng `40P01` mới, có
    chủ ý, mọi dạng đều đóng (một bên bị hủy, không bên nào lọt):
    - giao dịch nhiều câu đã giữ dòng version từ một câu trước (một lần ghi bất kỳ trên bảng của `_BUMPED_TABLES`) rồi ở
      câu sau lấy dòng tenant `FOR UPDATE` (gỡ một chủ `active`, hay đình chỉ một chủ), xen giữa là lần đình chỉ một
      người không phải chủ bất kỳ ở cùng tenant, giữ `FOR KEY SHARE` và chờ dòng version. Khi người đó là P (K2) hôm nay
      cả hai được nhận và tenant còn 0 chủ; khi là người khác hôm nay cả hai được nhận đúng, sau ticket này một bên bị
      hủy. Cùng giao dịch nhiều câu đó cạnh lần đình chỉ một chủ đã `40P01` từ trước, vì thứ tự version rồi tenant của
      nó ngược thứ tự chung;
    - hai lần đình chỉ người không phải chủ, cả hai vừa thành chủ trong lúc chờ cùng một lần xét đang mở, hay một lệnh
      hoặc một giao dịch đình chỉ người không phải chủ trước rồi một chủ sau, cạnh một lệnh như thế: cả hai giữ
      `FOR KEY SHARE` rồi cùng nâng lên `FOR UPDATE`. "Không `40P01`" của tiêu chí là cho lệnh một dòng như các ca của K.
      Dạng của ticket 08 (`check_owner_coverage` cạnh `refuse_losing_the_last_owner`) không rộng thêm: UPDATE không đổi khóa
      của nó lấy `FOR NO KEY UPDATE`, không xung đột với `FOR KEY SHARE` (K4 (ii)).
    - Không bảng, cột, quyền vai, hàm mới, trigger mới hay route, nên `test_rls_coverage.py`, `test_privileges.py` và
      `test_offboarding_coverage.py` không đổi và phải xanh.
    - Downgrade dựng lại thân của ticket 12 (từ chính module `_earlier`).

2. **Test** (integration, tệp mới `packages/python/dw_platform/tests/integration/test_last_owner_races.py`; không sửa
   `test_role_administration_db.py`, `test_membership_change_of_person.py` hay `test_role_write_races.py`): mỗi ca trên
   tenant gieo mới dưới `dw_migrator`, chủ sở hữu và người như `plant_world`; mỗi lần đình chỉ `UPDATE
platform.tenant_members SET status = 'suspended' WHERE tenant_id = :t AND user_id = :u`; mọi bên dưới `dw_migrator`
   (luật chủ cuối áp cho mọi người ghi, như quyết định (4) lượt xác nhận gate ticket 12). Ca đồng thời theo dạng `_race`
   của `test_service_principals_db.py:410-440` (bên thứ nhất giữ giao dịch mở, bên thứ hai chạy trong một task tới khi
   chờ khóa hay đã xong, bên thứ nhất commit; không ngủ cố định); harness đếm SQLSTATE `40P01` riêng, phải là 0 ở mọi ca
   trừ ca xen giữa của K2. Ca xen giữa của K2 có ba bước (A câu 1; lần đình chỉ P trong một task tới khi chờ khóa; A câu
   2 rồi commit) và bắt `DBAPIError` ở câu 2, ở lần commit của A và ở task của lần đình chỉ; nó không khẳng định bên nào bị
   hủy (bên nào hết `deadlock_timeout` trước thì bị chọn), chỉ đúng một bên, SQLSTATE 23514 hay `40P01`. Ca ba bên của K3
   cho hai task chạy tới khi cả hai chờ khóa trước khi bên thứ nhất commit. Sau mỗi ca: `platform.active_tenant_owners` của tenant có ít nhất một người, và mỗi lần từ
   chối khẳng định 23514 `ck_role_assignments_last_owner` và trạng thái của P không đổi.
3. `reviewing-feature-security` (ranh giới 1, 2, 6; 3 và 5 không áp: không đường agent hay tool, lần đình chỉ là SQL của
   người vận hành và audit của nó thuộc script, ADR-0104 (Accepted) mục 6), `mutations/13.yaml` một đột biến mỗi dòng ở cột "Đột biến" dưới đây,
   không chạy `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng tay. Độ trễ: câu khóa thêm chỉ chạy khi
   một thành viên không phải chủ rời `active`, không route nào làm việc đó, nên không có thao tác nào để đo ở lúc đóng
   hàng đợi (`.claude/rules/latency.md`); ghi điều đó ở Comments khi đóng ticket.

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                                                             | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Đột biến (`mutations/13.yaml`)                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| K1  | Đổi người cạnh đình chỉ người mới không làm mất chủ `active` cuối                     | Tenant `active` (rồi, ca riêng, `locked`), Q là chủ `active` duy nhất qua M; P là thành viên công ty `active` chưa có membership ở workspace của M. Đồng thời, hai thứ tự, đúng bên thứ hai bị từ chối với 23514 `ck_role_assignments_last_owner`: (i) đổi M sang P rồi đình chỉ P; (ii) đình chỉ P rồi đổi M sang P. Đối chứng: đình chỉ một người R không phải chủ cạnh đổi M sang P → cả hai nhận, P là chủ `active`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | (a) bỏ câu `PERFORM ... FOR KEY SHARE` (cả hai thứ tự đỏ: hai bên nhận, 0 chủ); (b) bỏ câu đọc lại thứ hai, trả sau khóa (thứ tự (i) đỏ)                           |
| K2  | Trao chủ trong một giao dịch cạnh đình chỉ người nhận không làm mất chủ `active` cuối | Tenant `active`, Q là chủ `active` duy nhất; bên A một giao dịch hai câu: gán `tenant_owner` cho membership của P, rồi gỡ lần gán `tenant_owner` của Q. Đồng thời, hai thứ tự, đúng bên thứ hai bị từ chối với 23514: (i) A trọn hai câu rồi đình chỉ P; (ii) đình chỉ P rồi A. Xen giữa (A câu 1, đình chỉ P chạy tới khi chờ khóa, A câu 2): đúng một bên bị hủy, SQLSTATE 23514 hay `40P01`, bên kia nhận; tenant còn đúng một chủ `active`. Thứ tự (ii) không giữ khóa mới (dòng version đã xếp hàng câu 1 của A sau lần đình chỉ, nên A đếm P đã `suspended` cả ở commit gốc): ca hồi quy                                                                                                                                                                                                                                                                                                                                                                                      | (a) như K1 (a) (thứ tự (i) và ca xen giữa đỏ)                                                                                                                      |
| K3  | Khóa thêm không làm hai lần đình chỉ hai chủ khóa chết                                | (i) Tenant `active` có đúng hai chủ `active` Q1, Q2: đình chỉ Q1 và đình chỉ Q2 đồng thời, hai thứ tự → bên thứ hai chờ rồi bị từ chối với 23514, không `40P01`. (ii) Ba bên: ba chủ `active` Q1, Q2, Q3; bên C gỡ lần gán `tenant_owner` của Q3 và giữ giao dịch mở (giữ dòng tenant `FOR UPDATE`); đình chỉ Q1 và đình chỉ Q2 ở hai kết nối, mỗi bên chạy tới khi chờ khóa; C commit → đúng một trong hai lần đình chỉ bị từ chối với 23514, bên kia nhận, không `40P01`, tenant còn đúng một chủ `active`                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | (a) câu `PERFORM ... FOR KEY SHARE` đặt trước câu đọc đầu, không điều kiện ((ii) đỏ: sau lần commit của C hai bên cùng giữ `FOR KEY SHARE` rồi cùng nâng, `40P01`) |
| K4  | Khóa thêm không chặn khóa ngoại, và không thêm `40P01` cạnh ticket 08                 | Tenant `active`. (i) Bên thứ nhất đình chỉ R (không phải chủ) và giữ giao dịch mở; bên thứ hai INSERT một dòng của một bảng có khóa ngoại tới `platform.tenants` mà không nằm trong `_BUMPED_TABLES` (`platform.workspaces` của tenant) → xong trong khi bên thứ nhất còn mở, không chờ khóa (harness khẳng định task của bên thứ hai xong trước lần commit của bên thứ nhất, không chỉ "không bị từ chối"). (ii) Gieo rồi khẳng định trước ca: `owner_coverage_low_since` NULL, `platform.checker_candidates(t, 'platform.roles.write', NULL)` đếm đúng 2, mọi khóa khác của `platform.owner_permission_keys()` đếm ít nhất 2; bên thứ nhất dưới `dw_migrator` gỡ lần gán `platform.roles.write` của một trong hai người đó (không phải chủ), đưa số đếm về 1, giữ giao dịch mở; bên thứ hai đình chỉ R chạy tới khi chờ dòng version; bên thứ nhất commit → cả hai nhận, 0 `40P01`, đúng một sự kiện `platform.tenant.owner_coverage_low` và `owner_coverage_low_since` khác NULL | (a) `FOR UPDATE` thay `FOR KEY SHARE` ((i) chờ, (ii) `40P01`, đỏ); (b) `FOR NO KEY UPDATE` thay `FOR KEY SHARE` ((ii) `40P01`, đỏ)                                 |

## Tiêu chí chấp nhận

- [ ] R6.7 (RB20): K1, lần đổi M (của chủ `active` cuối Q) sang P `active` và lần đình chỉ P đồng thời, ở tenant `active`
      và `locked`, cả hai thứ tự, cho đúng bên thứ hai 23514 `ck_role_assignments_last_owner`, không `40P01`, và tenant
      còn một chủ `active`; ca đình chỉ người không phải chủ cạnh lần đổi nhận cả hai; sai nếu cả hai bên được nhận, ca
      đối chứng bị từ chối, hay một trong hai đột biến của K1 vẫn xanh. Ở commit gốc (sau ticket 12) cả hai thứ tự nhận
      cả hai bên và tenant còn 0 chủ `active`.
- [ ] R6.7 (RB20): K2, lần trao chủ hai câu (gán P, gỡ Q) và lần đình chỉ P đồng thời cho đúng bên thứ hai 23514 ở cả hai
      thứ tự, không `40P01`; ở ca xen giữa đúng một bên bị hủy (23514 hay `40P01`) và tenant còn đúng một chủ `active`;
      sai nếu một ca kết thúc với 0 chủ `active`, hay đột biến của K2 vẫn xanh. Ở commit gốc thứ tự (i) và ca xen giữa nhận
      cả hai bên; thứ tự (ii) đã từ chối A ở commit gốc và giữ làm ca hồi quy.
- [ ] R6.7 (RB20): K3, hai lần đình chỉ hai chủ đồng thời xếp hàng: ở ca hai bên, cả hai thứ tự, đúng bên thứ hai bị
      từ chối với 23514; ở ca ba bên, sau lần commit của C, đúng một lần đình chỉ bị từ chối với 23514; không `40P01` ở ca
      nào; sai nếu một bên `40P01` hay cả hai nhận, hay đột biến của K3 vẫn xanh.
- [ ] R6.7 (RB20): K4, lần đình chỉ người không phải chủ đang mở không chặn lần INSERT có khóa ngoại tới tenant, và
      cạnh lần gỡ hạ người giữ `platform.roles.write` xuống dưới hai cả hai được nhận, 0 `40P01`, đúng một sự kiện
      `platform.tenant.owner_coverage_low`; sai nếu bên thứ hai chờ ở (i), có `40P01` ở (ii), hay một trong hai đột biến
      của K4 vẫn xanh.
- [ ] Xong: `uv run python -m pytest packages/python/dw_platform/tests/integration/test_last_owner_races.py packages/python/dw_platform/tests/integration/test_role_administration_db.py packages/python/dw_platform/tests/integration/test_membership_change_of_person.py packages/python/dw_platform/tests/integration/test_role_write_races.py packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py` xanh.

## Nguồn

- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:870-932`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:898-910`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:923`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1126-1131` (R6.7); `db/migrations/versions/b5677d345bc1_tenant_roles.py:499-512` (`active_tenant_owners`).
- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1066-1067` (`check_owner_coverage` ghi `platform.tenants`); bước 1 của ticket 08; bước 1 của ticket 12 (nhánh `memberships`, thứ tự khóa).
- `db/migrations/versions/349080a62e41_tenant_members.py:93-110` (khóa của `tenant_members`); `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100` (`_earlier`, `_patched`).
- `packages/python/dw_platform/tests/integration/test_role_administration_db.py:192-232`, `packages/python/dw_platform/tests/integration/test_role_administration_db.py:733-850`, `packages/python/dw_platform/tests/integration/test_service_principals_db.py:389-440`, `packages/python/dw_platform/src/dw_platform/testing/rbac.py:41-165`.
- Spec: R6.7, RB20; ADR-0104 (Accepted) mục 6 ("keeps one active `tenant_owner`"), Amendments 2026-11-03 (`locked`); MEDIUM (a) của hai lượt gate ticket 12.

## Comments

- 2026-11-06 (agent, theo ủy quyền 31/10/2026): cắt từ MEDIUM (a) lượt đầu và (a) lượt xác nhận của gate ticket 12. Không
  gộp vào ticket 12: 12 đã ĐẠT và lane 1 sắp dựng; sửa không phải một dòng thêm vào bước của 12 (hai câu đọc, chọn chế
  độ khóa, và bốn kiểm soát đồng thời của riêng nó), và lối trao chủ hai câu (K2) có từ ticket 03, không cần lần đổi
  người. `Blocked by: 12`, không phải 08: ticket 08 không sửa hàm này (nó thay `owner_coverage_after_write`,
  `rbac_refusals` và hàm tách nhiệm), còn 12 thay thân hàm bằng `CREATE OR REPLACE`; một revision dựng từ thân trước 12
  sẽ xóa nhánh `memberships` của 12, và K1 chỉ có sau 12. 08 đến qua chuỗi (12 chờ 11, 11 chờ 08, 09), nên K4 (ii) chạy
  trên trigger hoãn của 08. Nếu sai thì: nhánh `ELSE` sửa trong revision của ticket 12 và K1-K4 thành bước 2 của 12,
  gate lại 12.
  Chọn `FOR KEY SHARE` có điều kiện thay vì khóa dòng tenant `FOR UPDATE` trước lần trả sớm (đề xuất của gate 12): đề xuất
  đó làm mọi lần đình chỉ cạnh lần ghi `owner_coverage_low_since` lúc commit của ticket 08 thành `40P01`, và chặn mọi khóa
  ngoại tới tenant trong lúc đình chỉ. Nếu sai thì (chế độ khóa cho `40P01` ở ca K4 (ii) dù đã đo): `FOR UPDATE` như đề
  xuất của gate 12, K4 (ii) đổi thành "đúng một bên bị hủy", và dạng `40P01` của 08 ghi rộng thêm ở Comments của 08.
  Ngoài ticket, có chủ ý: lần chuyển tenant `setup` sang `active` (R3.10: `guard_tenant_setup` đếm hai chủ trong ảnh
  chụp của nó, `db/migrations/versions/b5677d345bc1_tenant_roles.py:801-818`) cạnh lần đình chỉ chủ có cùng dạng: ở tenant
  `setup` phần chung trả trước khóa dòng tenant, nên tenant có thể thành `active` với ít hơn hai chủ, kể cả không chủ nào
  khi cả hai bị đình chỉ cùng lúc. Sai về phía mở, nhưng chủ là R3.10 (lần chuyển trạng thái tenant), không phải nhánh này;
  phiên điều phối cắt một ticket của R3.10. Nếu sai thì: nhánh `ELSE` khóa cả khi tenant `setup`, trong revision này.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk một
  subagent, ranh giới 1, 2, 3, 5, 6). `check_plans.py` 24 Đạt. Hai HIGH, sửa ở ticket: (1) K4 (i) cũ đòi lần đình chỉ thứ
  hai không chờ khóa, nhưng mọi UPDATE trên `tenant_members` lấy dòng version (`trg_z_bump_access_version`), nên tiêu chí
  đỏ trên code đúng: bỏ ca đó; đột biến `FOR NO KEY UPDATE` đỏ ở K4 (ii), `FOR UPDATE` ở K4 (i), (ii). (2) Đột biến K3 (a)
  (khóa vô điều kiện) xanh với harness hai bên, vì bên thứ nhất nâng khóa một mình trước khi bên thứ hai xin: thêm ca ba
  bên K3 (ii), một lần gỡ chủ thứ ba giữ `FOR UPDATE` để hai lần đình chỉ cùng chờ rồi cùng thức. MEDIUM, sửa: (3) câu
  khóa chỉ lấy ở tenant `active`, `locked`, để không chờ `complete_tenant_setup` ở tenant `setup`; (4) dạng `40P01` mới
  nêu đủ (lần đình chỉ bất kỳ người không phải chủ cạnh giao dịch nhiều câu đã giữ dòng version rồi lấy `FOR UPDATE`, và
  hai lần nâng khóa cùng lúc); (5) ca xen giữa của K2 không khẳng định bên nào bị hủy. LOW, sửa: (6) bảo đảm là của READ
  COMMITTED. Quyết định: (7) nhận dạng `40P01` của (4) (agent, theo ủy quyền 31/10/2026): mọi dạng đều đóng, dạng có
  P hôm nay là lỗ 0 chủ, dạng không có P cần một giao dịch nhiều câu gỡ chủ, mà repo không có route đình chỉ; Nếu sai
  thì: thứ tự khóa của giao dịch nhiều câu (dòng tenant trước dòng version ở câu đầu) là một ticket của ticket 08 hay
  của service gán vai trò, và service thử lại một lần khi `40P01`. MEDIUM, không sửa, người dựng đọc trước: (a) hai lối
  R6.7 khác vẫn để 0 chủ dưới lần ghi đồng thời và không ticket nào nhận: lần xóa dòng công ty hay người dùng của P cạnh
  lần trao chủ (`remove_owner_assignments_first` đọc khi lần trao chưa commit, rồi nhánh `role_assignments` trả sớm vì
  dòng công ty của P đã mất,
  `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:913-916`), và lần kích hoạt lại Q
  (đang giữ `tenant_owner`) cùng đình chỉ chủ cuối X cạnh lần gỡ lần gán của Q (lần gỡ thấy Q chưa `active`, trả sớm
  không khóa); phiên điều phối cắt một ticket của R6.7 cho hai lối đó. Nếu sai thì: mọi nhánh trả sớm của
  `refuse_losing_the_last_owner` lấy `FOR KEY SHARE` như nhánh ở đây, trong revision này. (b) Câu "R6.7 nay đúng cả dưới
  lần đình chỉ đồng thời" của dòng Quyết định spec chỉ cho lối đình chỉ, như (a) nói. (c) Lần đình chỉ đang mở ở tenant B
  không chặn lần gỡ chủ ở tenant A (khóa trên dòng của từng tenant): không ca riêng.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới, builder check và boundary walk một
  subagent, ranh giới 1, 2, 3, 5, 6). `check_plans.py` 24 Đạt. 0 CRITICAL, 0 HIGH. MEDIUM, sửa ở thân: (1) thứ tự (ii)
  của K2 không đỏ khi bỏ khóa mới (dòng version xếp hàng câu 1 của A sau lần đình chỉ): ghi là ca hồi quy, đột biến K2 (a)
  đỏ ở (i) và ca xen giữa; (2) K4 (ii) nêu trạng thái gieo, để lần gỡ thật sự qua ngưỡng hai người; harness K4 (i) khẳng
  định bên thứ hai xong trước lần commit; bước 3 nêu ranh giới 2 và vì sao 3, 5 không áp. MEDIUM, không sửa, người dựng đọc
  trước: (a) vế `status IN ('active', 'locked')` của câu khóa không có ca hay đột biến (bỏ nó mọi K vẫn xanh); người dựng
  thêm ca tenant `setup` được. (b) Đột biến K3 (a) đỏ khi hai lần đình chỉ cùng thức sau lần commit của C và cùng được
  `FOR KEY SHARE` trước khi bên nào nâng: chạy đột biến vài lần, một lần `40P01` là đỏ; không lần nào đỏ thì ghi ở
  Comments, không đổi chế độ khóa. (c) Ca xen giữa của K2 sau sửa luôn tạo vòng nên thường ra `40P01`; "23514 hay
  `40P01`" giữ vì bên bị chọn tùy `deadlock_timeout`. (d) `active` sang `invited` cùng nhánh với đình chỉ, không ca riêng;
  lệnh nhiều dòng như (4) lượt trước. (e) Bên bị hủy `40P01` không có ánh xạ lỗi API vì không route nào đình chỉ; quyết
  định (7) lượt trước giữ. Sửa sau lượt này không được người đọc mới đọc lại; người dựng đọc K2, K4 trước.
- 2026-11-06 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
