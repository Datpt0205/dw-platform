# 11 — Tách nhiệm dưới hai lần ghi đồng thời, và lần đổi người của membership

Status: resolved (2026-11-06, main)
Blocked by: 08, 09
Area: studio
Yêu cầu: R5.1, RB14, R3.12

## Mục tiêu

R5.1 và RB14: không ai giữ khóa của cả hai vế một luật tách nhiệm chưa có miễn trừ đã xác nhận, "và không đổi gì". Hôm
nay điều đó chỉ đúng cho từng lần ghi một mình. Trigger tách nhiệm `platform.enforce_role_separation_of_duties` là trigger
AFTER theo dòng, bắn trước `trg_z_bump_access_version` (trigger AFTER theo dòng bắn theo thứ tự tên), nên hai giao dịch
đồng thời, mỗi bên đưa cho cùng một người một vế (gán L và gán R; thêm khóa vế phải vào vai trò người đó giữ và gán L;
sau ticket 09, khôi phục R và gán L), mỗi bên xét trước khi bên kia commit, cùng qua, rồi người đó giữ cả hai vế: trái
R5.1 và ADR-0104 (Accepted) mục 9 ("refuse a change leaving any holder in breach"). Thêm một đường không cần đồng thời:
`dw_migrator` đổi `platform.memberships.user_id` mang mọi lần gán của membership sang người khác mà không trigger tách
nhiệm nào xét. Ticket này đo cuộc đua như Câu 3 của discovery/08 đo cuộc đua thu hồi, rồi cho trigger tách nhiệm khóa
dòng version của công ty trước khi đọc, và xét lần đổi người. Cùng lúc nó đo và giữ bằng test cuộc đua của cảnh báo dưới
hai người (R3.12, RB40), mà ticket 08 cho chạy lúc commit.

## Việc cần làm

Đọc ở `0721f156` (5/11/2026):

- Hai trigger tách nhiệm `AFTER INSERT OR UPDATE ... FOR EACH ROW` trên `platform.role_assignments` và
  `platform.tenant_role_permissions` (`db/migrations/versions/b5677d345bc1_tenant_roles.py:1161-1166`); trigger tăng
  version `trg_z_bump_access_version` cũng AFTER theo dòng trên cùng bảng (`b5677d345bc1_tenant_roles.py:1151-1156`),
  `UPDATE platform.tenant_access_versions` (`b5677d345bc1_tenant_roles.py:752-754`), tên chữ `z` để bắn sau cùng. Nên
  khóa dòng version của bên thứ hai đến sau lần xét tách nhiệm của nó: nó chờ bên thứ nhất commit rồi commit, không
  đọc lại.
- Thân hàm tách nhiệm (`b5677d345bc1_tenant_roles.py:584-628`; ticket 08 viết lại ở bước 3, ticket 09 thêm nhánh
  `tenant_roles`): `v_people` rồi `platform.sod_violation` (plpgsql `VOLATILE`, `b5677d345bc1_tenant_roles.py:546-580`),
  nên ở READ COMMITTED mỗi câu trong hàm lấy snapshot mới: một câu chạy sau khi chờ được khóa thấy lần ghi vừa commit,
  như ghi chú của `platform.refuse_revoking_a_waiver_in_use` (`b5677d345bc1_tenant_roles.py:642-644`) dựa vào.
- Câu 3 của discovery/08 (`db/bench/rbac/RESULTS.md:168-197`, harness `db/bench/rbac/bench_rbac.py:1151-1280` ở `0721f156`; ticket 08 đang sửa tệp này nên số dòng sẽ dời, tìm theo tên hàm) đo hai
  cuộc đua thu hồi (miễn trừ, quyền của người gán): 0/200 lọt ở head nhờ `FOR SHARE`, 196/200 và 99/200 khi bỏ nó, đột
  biến làm trong database đo bằng `pg_get_functiondef` và kiểm `md5(prosrc)`. Cuộc đua của ticket này khác: hai bên
  cùng chèn hay sửa dòng mới, không dòng có sẵn nào để `FOR SHARE`, nên chưa đo và chưa có khóa nào.
- Đổi danh tính membership: `platform.guard_membership_identity` từ chối mọi người ghi trừ `dw_migrator`
  (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1000-1015`, trigger
  `d2b57239ef50_role_administration_and_anti_escalation.py:1144-1146`; ADR-0104 (Accepted) Amendments 2026-11-04 mục 10).
  Khóa ngoại `fk_role_assignments_tenant_id_memberships` trên `(tenant_id, workspace_id, membership_id)` không
  `ON UPDATE CASCADE` (`b5677d345bc1_tenant_roles.py:159-161`), nên đổi `tenant_id` hay `workspace_id` của membership còn
  lần gán bị khóa ngoại từ chối; chỉ đổi `user_id` mang lần gán sang người khác. `memberships` có trong `_BUMPED_TABLES`
  (`b5677d345bc1_tenant_roles.py:759-767`).
- Mọi lần ghi đổi khóa một người giữ cho tách nhiệm đều tăng version của chính công ty đó: `tenant_roles`,
  `tenant_role_permissions`, `role_assignments`, `memberships` đều trong `_BUMPED_TABLES`. Miễn trừ (`sod_waivers`) không
  tăng version; cuộc đua thu hồi miễn trừ đã có `FOR SHARE` (Câu 3 a). `platform.sod_rules` chỉ migration ghi. Khóa
  `obj.*`/`fld.*` không thuộc luật nào sau ticket 09 (`ck_sod_rules_no_generated_keys`).
- Tiền lệ test hai kết nối thật: `_race` của
  `packages/python/dw_platform/tests/integration/test_service_principals_db.py:407-437` (bên thứ nhất ghi và giữ giao
  dịch, bên thứ hai chạy trong một task tới khi `pg_stat_activity.wait_event_type = 'Lock'`, `_blocked`, `_until` ở
  `test_service_principals_db.py:386-401`, rồi bên thứ nhất commit).

Việc:

1. **Đo trước** (trên head sau ticket 09, chưa sửa): thêm vào `db/bench/rbac/bench_rbac.py` các cuộc đua dưới, mỗi cuộc
   200 lượt với lịch `schedule()` của Câu 3 (`bench_rbac.py:1248-1266` ở `0721f156`; lượt chẵn bên thứ nhất giữ khóa trước, lượt lẻ
   ngược lại, seed cố định), hai phiên mỗi phiên một kết nối giữ suốt các lượt, trên công ty nhỏ của Câu 3 (thêm người nếu
   cần). Lọt là: sau lượt, người đó giữ cả hai vế của một luật không miễn trừ được (đọc `platform.sod_violation`), hay ở
   (d) số sự kiện khác một.
    - (a) Hai lần gán: bên này gán vai trò vế trái L cho P qua membership ở workspace A, bên kia gán vai trò vế phải R cho
      P qua membership ở workspace B, cả hai dưới `dw_app` với đề xuất xác nhận trong chính giao dịch như service ghi.
    - (b) Khóa vào vai trò: P giữ vai trò X; bên này thêm khóa vế phải vào X, bên kia gán L cho P. Dự đoán chỉ lọt ở
      lượt lần gán đi sau (khoảng 100/200): một lần ghi `tenant_role_permissions` đã khóa dòng version trước khi trigger
      tách nhiệm của nó đọc, vì `trg_tenant_role_permissions_role_version` (tên xếp trước) `UPDATE platform.tenant_roles`
      và `trg_z_bump_access_version` của `tenant_roles` bắn trong lần ghi lồng đó
      (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:838-858`, `:1123-1125`). Đó cũng là
      tiền lệ của bước 2: khóa dòng trước khi đọc.
    - (c) Khôi phục: R xóa mềm có lần gán của P; bên này khôi phục R dưới `dw_migrator` (trigger của ticket 09), bên kia
      gán L cho P.
    - (d) Cảnh báo dưới hai người: công ty `active` với đúng ba người giữ `platform.roles.write`, dựng như K1 của ticket 08;
      mỗi bên gỡ lần gán của một người khác nhau. Đúng một sự kiện `platform.tenant.owner_coverage_low` sau lượt là
      không lọt. Theo bước 1 của ticket 08 lần kiểm chạy lúc commit, sau khi lệnh gỡ đã khóa dòng version của công ty, nên
      dự đoán 0 lọt (chưa đo).
    - (e) Thứ tự khóa đảo: bước 2 lấy dòng version trước `FOR SHARE` trên miễn trừ của `platform.sod_violation`, hôm nay
      ngược lại. Bên này xác nhận (hay thu hồi) miễn trừ W rồi, trong cùng giao dịch, gán một vai trò cho người khác;
      bên kia gán vế phải cho người đang dựa vào W. Dạng này cho một `40P01` mới (một bên bị hủy, không bên nào lọt).
      Ở `0721f156` chỉ `packages/python/dw_platform/src/dw_platform/adapters/persistence/separation_of_duties_repo.py`
      ghi `platform.sod_waivers` (miễn trừ, thu hồi, mỗi lần một giao dịch không ghi bảng vai trò) và bước xóa của
      offboarding (chỉ DELETE); người dựng tìm lại và ghi kết quả cạnh số đo. Một đường mới ghi miễn trừ rồi ghi vai trò
      trong cùng giao dịch thì khóa dòng version của công ty trước khi ghi miễn trừ (một thứ tự: dòng version trước), và
      ticket của đường đó mang test của nó.
    - Chạy lại hai cuộc đua của Câu 3 (`race_sod`, cuộc đua quyền của người gán), để bước 2 không làm hỏng chúng.
      Mọi cuộc đua đếm thêm số lần SQLSTATE `40P01` (deadlock) và `40001`.
2. **Sửa**: một revision (id hex của `alembic revision`) `CREATE OR REPLACE` `platform.enforce_role_separation_of_duties()`
   dựng từ thân ticket 09 để lại, nạp bằng `_earlier()` và sửa bằng `_patched()` (neo khớp đúng một lần,
   `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100`), không chép tay:
    - Câu đầu tiên của thân, trước `v_people`, trước câu theo tập của ticket 08 và trước mọi nhánh:
      `PERFORM 1 FROM platform.tenant_access_versions v WHERE v.tenant_id = NEW.tenant_id FOR NO KEY UPDATE;` rồi
      `IF NOT FOUND THEN RAISE EXCEPTION ... USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_roles_sod_access_version'`.
      Cùng chế độ khóa mà `UPDATE` của `platform.bump_access_version()` lấy trên cùng dòng ở cuối cùng lệnh, nên giao dịch
      không giữ khóa nào mà nó không giữ hôm nay, chỉ lấy sớm hơn trong cùng lệnh: bên thứ hai chờ ở đây thay vì ở
      `trg_z_bump_access_version`, rồi đọc lại với snapshot mới. Thiếu dòng version: công ty
      `offboarding` hay `offboarded` thì xét tiếp không khóa, mọi trạng thái khác thì từ chối (fail closed). Dòng chỉ vắng
      sau bước xóa của offboarding (`platform.purge_tenant_access_version`, `b5677d345bc1_tenant_roles.py:770-792`, chỉ
      chạy khi công ty `offboarding`); ở đó lần ghi duy nhất còn tới trigger là UPDATE do `ON DELETE SET NULL` của
      `fk_role_assignments_assigned_by_users` (`b5677d345bc1_tenant_roles.py:165-166`) khi xóa một người dùng, và lần
      ghi nới ở đó đã bị `platform.rbac_refusals` từ chối (ADR-0104 (Accepted) Amendments 2026-11-04 mục 6).
    - Nhánh mới `TG_TABLE_NAME = 'memberships'`: `v_people := ARRAY[NEW.user_id]`, rồi cùng phần xét chung với
      `NEW.tenant_id`, nên cùng 23514 `ck_roles_sod_memberships`, `HINT`, `DETAIL` như R5.1. Không trả sớm: đổi người của
      một membership không có lần gán nào, hay chỉ có vai trò ngoài luật, sang một người đã vi phạm sẵn ở `NEW.tenant_id`
      cũng bị từ chối, như lần khôi phục của ticket 09 và ADR-0104 (Accepted) mục 9 ("refuse a change leaving any
      holder in breach"). Chỉ `NEW.tenant_id` được xét, không tenant khác của người đó. Nhánh không đọc `NEW.role_id`,
      `NEW.membership_id` hay `NEW.permission_key`.
    - `CREATE TRIGGER trg_memberships_separation_of_duties AFTER UPDATE OF user_id ON platform.memberships FOR EACH ROW
WHEN (NEW.user_id IS DISTINCT FROM OLD.user_id) EXECUTE FUNCTION platform.enforce_role_separation_of_duties()`.
      Không xét người ghi, như hai trigger hiện có: `dw_migrator` cũng bị từ chối.
    - Nếu (d) của bước 1 lọt, cùng revision thêm câu khóa đó (cùng chế độ) ở đầu
      `platform.owner_coverage_after_write()` của ticket 08, dựng cùng cách, nhưng thiếu dòng thì bỏ qua lần khóa, không
      từ chối: trigger đó bắn cả trên DELETE của offboarding, và cảnh báo không phải lần từ chối; (d) không lọt thì hàm đó không đổi và
      Comments ghi số đo.
    - Downgrade dựng lại đúng thân ticket 09 để lại (và thân ticket 08 của `owner_coverage_after_write` nếu đã đổi), DROP
      trigger mới. Không bảng, quyền vai, hàm mới hay bước offboarding mới, nên `test_rls_coverage.py`,
      `test_privileges.py` và `test_offboarding_coverage.py` không đổi và phải xanh. Mốc `down_revision` của test vi sai
      của ticket 08 giữ nguyên, cùng lý do ticket 09 ghi ở bước 3 của nó: tập lần ghi của test đó không có lần ghi đồng
      thời, không đổi `user_id`, không xóa dòng version, nên mọi dòng vẫn bằng nhau ở hai database; MEDIUM (h) của 08 dời
      mốc chỉ cho lần viết lại không đổi câu trả lời nào, còn ticket này thêm đúng hai lần từ chối mới.
3. **Đo sau**: chạy lại bước 1 trên head mới; rồi đột biến trong database đo như Câu 3 (`without_lock`,
   `bench_rbac.py:1173-1202` ở `0721f156`: bỏ đúng một câu `PERFORM ... FOR NO KEY UPDATE;`, kiểm `md5(prosrc)` đổi rồi về đúng bản
   gốc) và chạy lại (a)-(c). Rồi `q2` của `make bench-rbac` (lần gán 1.000 người; "thêm 10 khóa, 10 lệnh") trên head
   trước và sau bước 2, cùng máy, trung vị ba lần mỗi bên. Ghi một mục mới của `db/bench/rbac/RESULTS.md` (bảng như Câu
   3: cuộc đua, trước, sau, đột biến; số lần `40P01`/`40001`; số `q2`) và tóm tắt vào Comments.
4. **Test** (integration, tệp mới `packages/python/dw_platform/tests/integration/test_role_write_races.py`; không sửa
   `test_tenant_roles.py`, `test_role_restore_separation_of_duties.py` hay tệp test của ticket 08): mỗi ca trên một tenant
   gieo mới dưới `dw_migrator`; luật test (bảng toàn cục) mang khóa riêng của ca trên khóa danh mục riêng của ca và được
   xóa (miễn trừ trước, rồi luật) ở phần dọn dẹp chạy cả khi test lỗi, như
   `packages/python/dw_platform/tests/integration/test_sod_waivers.py:110-138`. Ca đồng thời theo dạng `_race` của
   `test_service_principals_db.py:407-437`: bên thứ nhất ghi và giữ giao dịch mở; bên thứ hai chạy trong một task tới khi
   nó chờ khóa (`wait_event_type = 'Lock'`, đọc bằng kết nối superuser như `_blocked`) hay đã xong; bên thứ nhất commit;
   rồi đợi bên thứ hai. Không ngủ cố định. Ở commit gốc bên thứ hai cũng chờ (ở `trg_z_bump_access_version`), nên thứ tự
   tất định ở cả hai phía của bước 2. Ca (a) chạy dưới `dw_app` với đề xuất xác nhận trong chính giao dịch (cách của
   `test_sod_waivers.py:197-274`); (b), (c), (d) dưới `dw_migrator` (tách nhiệm không xét người ghi). Dòng Xong gồm
   `test_role_trigger_cost_db.py`, tệp test của ticket 08; Comments của 08 đặt tên khác thì dòng Xong theo tên đó.
5. `reviewing-feature-security` (ranh giới 1, 2, 3, 5, 6), `mutations/11.yaml` một đột biến mỗi dòng ở cột "Đột biến" dưới đây,
   không chạy `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng tay.

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                            | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Đột biến (`mutations/11.yaml`)                                                                                                                                                                                                                |
| --- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | Hai lần ghi đồng thời không để ai giữ cả hai vế      | (a) gán L cho P ở A giữ mở, gán R cho P ở B chờ, bên thứ nhất commit → bên thứ hai 23514 `ck_roles_sod_memberships`, `DETAIL` có P, P không giữ R; (b) khóa vế phải vào X giữ mở, gán L chờ → gán L bị từ chối; (c) khôi phục R giữ mở, gán L chờ → gán L bị từ chối. Đối chứng: cùng (a) với luật có miễn trừ đã xác nhận → cả hai nhận; cùng (a) cho hai người khác nhau → cả hai nhận; tenant A giữ mở một lần gán, một lần gán ở tenant B không chờ (không `wait_event_type = 'Lock'`) và nhận                                                                                                                                            | (a) bỏ câu `PERFORM ... FOR NO KEY UPDATE`; (b) chuyển câu khóa xuống sau phần xét chung (trước `RETURN NULL`); (c) khóa `FOR KEY SHARE` thay cho `FOR NO KEY UPDATE`; (d) câu khóa bỏ `WHERE v.tenant_id = NEW.tenant_id` (ca hai tenant đỏ) |
| K2  | Thiếu dòng version thì từ chối, trừ khi offboarding  | Xóa dòng `platform.tenant_access_versions` của tenant dưới `dw_migrator`, công ty `active`, gán L cho P → 23514 `ck_roles_sod_access_version`. Đối chứng: công ty `offboarding`, dòng đã xóa, xóa người dùng U đã gán một vai trò (`assigned_by` về NULL) → nhận                                                                                                                                                                                                                                                                                                                                                                              | (a) `IF NOT FOUND` không raise; (b) bỏ phép miễn của `offboarding`/`offboarded` (ca đối chứng đỏ)                                                                                                                                             |
| K3  | Đổi người của membership qua tách nhiệm              | P giữ L; membership M của Q có lần gán R; `UPDATE platform.memberships SET user_id = P WHERE id = M` dưới `dw_migrator` → 23514 `ck_roles_sod_memberships`, `DETAIL` có P, M vẫn của Q. M không có lần gán nào (hay chỉ vai trò ngoài luật) đổi sang P đã vi phạm sẵn (luật thêm sau các lần gán) → cũng từ chối. Đối chứng: M chỉ có vai trò ngoài luật đổi sang P không vi phạm → nhận; P là thành viên tenant A và B, vi phạm sẵn ở B, đổi M ở A (chỉ vai trò ngoài luật) sang P → nhận; `SET user_id = user_id` (cùng giá trị; `UPDATE OF user_id` vẫn bắn) trên membership của P khi P đã vi phạm sẵn (luật thêm sau các lần gán) → nhận | (a) bỏ trigger mới; (b) nhánh `memberships` lấy `OLD.user_id`; (c) bỏ mệnh đề `WHEN` (ca cùng giá trị đỏ); (d) nhánh `memberships` xét mọi tenant mà P là thành viên (ca hai tenant đỏ)                                                       |
| K4  | Cảnh báo dưới hai người đúng một lần dưới hai lần gỡ | Ba người giữ `platform.roles.write`; gỡ lần gán của người thứ hai giữ mở, gỡ của người thứ ba chờ, bên thứ nhất commit → sau cả hai commit đúng một sự kiện `platform.tenant.owner_coverage_low` và `owner_coverage_low_since` khác NULL                                                                                                                                                                                                                                                                                                                                                                                                      | trigger ràng buộc của ticket 08 trên `role_assignments` đổi sang `INITIALLY IMMEDIATE` và xếp tên trước `trg_z_bump_access_version` (lần kiểm chạy trước khi khóa)                                                                            |

## Tiêu chí chấp nhận

- [x] R5.1: K1, ba ca đồng thời (a), (b), (c) từ chối bên thứ hai với 23514 `ck_roles_sod_memberships`, `DETAIL` có P, và
      sau đó P không giữ vế bên thứ hai mang; ba ca đối chứng nhận cả hai bên, bên tenant B không chờ; sai nếu một bên thứ hai được nhận, một ca
      đối chứng bị từ chối, hay một trong bốn đột biến của K1 vẫn xanh. Ở commit gốc ba ca đồng thời nhận cả hai bên.
- [x] RB14: K2, lần gán trên tenant `active` thiếu dòng version bị từ chối với `ck_roles_sod_access_version`, ca
      offboarding được nhận; sai nếu lần gán được nhận, ca offboarding bị từ chối, hay một trong hai đột biến của K2 vẫn
      xanh.
- [x] R5.1: K3, lần đổi `user_id` làm P giữ cả hai vế bị từ chối với `ck_roles_sod_memberships` và M giữ `user_id` cũ; ca
      M không mang khóa thuộc luật sang P đã vi phạm sẵn bị từ chối; ca hai tenant và ca cùng giá trị được nhận; sai nếu lần đổi đó được nhận, một ca đối chứng bị từ chối, hay một trong bốn đột biến của K3 vẫn
      xanh. Ở commit gốc lần đổi được nhận.
- [x] R3.12: K4, đúng một sự kiện sau hai lần gỡ đồng thời; sai nếu không có hay có hai sự kiện, hay đột biến của K4
      vẫn xanh. Ở commit gốc (sau ticket 08) dự đoán đã đúng: test này là lớp giữ, và điều làm nó đỏ được là đột biến
      của K4; nếu ở commit gốc nó đỏ thì (d) lọt và bước 2 thêm khóa vào `owner_coverage_after_write()`.
- [x] R5.1: mục mới của `db/bench/rbac/RESULTS.md` có, cho (a)-(d) và hai cuộc đua của Câu 3, số lọt trên 200 lượt trước
      bước 2, sau bước 2 và với đột biến trong database (kèm `md5` trước, đột biến, khôi phục), cùng số `40P01` và
      `40001`; sai nếu sau bước 2 một cuộc đua lọt, có một deadlock, hay đột biến của (a)-(c) không lọt lần nào. Cùng mục
      có `q2` trước và sau (trung vị ba lần): sai nếu trung vị lần gán 1.000 người hay "thêm 10 khóa" xấu hơn 10% mà không
      ghi lý do cạnh số đo (`.claude/rules/latency.md`). Khóa vẫn lấy mỗi lần trigger bắn dù số đo thế nào: không dấu
      theo giao dịch, vì một GUC `dw_app` đặt sẵn được thì bỏ được khóa (MEDIUM (a) của ticket 08). Cuộc đua (e) không
      tính vào "không deadlock": số `40P01` của nó ghi riêng cùng kết quả tìm nơi ghi miễn trừ và vai trò trong một giao
      dịch; sai nếu (e) có một lần lọt.
- [x] Xong: `uv run python -m pytest packages/python/dw_platform/tests/integration/test_role_write_races.py packages/python/dw_platform/tests/integration/test_role_restore_separation_of_duties.py packages/python/dw_platform/tests/integration/test_separation_of_duties.py packages/python/dw_platform/tests/integration/test_sod_waivers.py packages/python/dw_platform/tests/integration/test_tenant_roles.py packages/python/dw_platform/tests/integration/test_service_principals_db.py packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py packages/python/dw_platform/tests/integration/test_offboarding.py packages/python/dw_platform/tests/integration/test_role_trigger_cost_db.py` xanh.

## Nguồn

- `db/migrations/versions/b5677d345bc1_tenant_roles.py:1151-1166` (thứ tự trigger), `db/migrations/versions/b5677d345bc1_tenant_roles.py:584-628` (`enforce_role_separation_of_duties`), `db/migrations/versions/b5677d345bc1_tenant_roles.py:546-580` (`sod_violation`), `db/migrations/versions/b5677d345bc1_tenant_roles.py:642-644`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:752-754` (tăng version), `db/migrations/versions/b5677d345bc1_tenant_roles.py:759-767` (`_BUMPED_TABLES`), `db/migrations/versions/b5677d345bc1_tenant_roles.py:159-161` (khóa ngoại của lần gán); spec: R5.1, RB14, R3.12.
- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1000-1015`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1144-1146` (danh tính membership).
- `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100` (`_earlier`, `_patched`).
- `db/bench/rbac/RESULTS.md:168-197` (Câu 3), `db/bench/rbac/bench_rbac.py:1151-1280` (harness Câu 3, ở `0721f156`).
- `packages/python/dw_platform/tests/integration/test_service_principals_db.py:386-437` (`_race`), `packages/python/dw_platform/tests/integration/test_sod_waivers.py:110-138`, `packages/python/dw_platform/tests/integration/test_sod_waivers.py:197-274`.
- ADR-0104 (Accepted) mục 7, 9, Amendments 2026-11-04 (mục 10, danh tính membership), Amendments 2026-11-05 (mục 9, ticket này); Comments của ticket 08 (MEDIUM (b), (c)) và ticket 09 (lượt xác nhận).

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cắt từ lượt xác nhận của gate ticket 09 (HIGH nhận rủi ro: hai giao dịch
  đồng thời cùng qua tách nhiệm, và đường `dw_migrator` đổi `memberships.user_id`) và MEDIUM (b) của gate ticket 08 (hai
  lần gỡ đồng thời không cảnh báo). (b) của 08 ghi chủ là R3.12, không phải ticket này; gộp vào đây vì cùng harness, cùng
  cách đo và cùng lời giải (dòng version), và ở đây chỉ đo và giữ bằng test, sửa chỉ khi số đo cho thấy lọt. Nếu sai thì:
  tách K4 và (d) thành ticket riêng của R3.12.
  Chọn khóa dòng version thay vì: khóa tư vấn theo (tenant, người) — nhánh quyền của vai trò và nhánh khôi phục phải khóa
  mọi người giữ (1.000 ở D12) theo thứ tự cố định, thêm một loại khóa mới và nguy cơ deadlock với nhánh gán, mà vẫn không
  phủ (d); SERIALIZABLE — đổi mức cô lập cho mọi người ghi (service, `dw_provisioner`, script `dw_migrator`), buộc mọi
  nơi gọi thử lại `40001`, và khóa vị từ trên các câu đọc trong hàm ở lần ghi 1.000 dòng; trigger tách nhiệm hoãn tới commit
  — lỗi của R5.3 chuyển ra COMMIT, và trong một giao dịch nhiều lệnh một vi phạm tạm thời được nhận, đổi câu trả lời của
  R5.1 "không đổi gì". Dòng version đã bị chính lệnh đó khóa tới commit (ADR-0104 (Accepted) mục 7, Phát hiện 6 của
  discovery/08), nên lời giải không thêm lần chờ nào giữa hai giao dịch, chỉ dời chỗ chờ lên trước lần đọc; chi phí là một
  lần tra chỉ mục và một lần khóa dòng mỗi lần trigger bắn, đo ở bước 3. Nếu sai thì: số `q2` xấu hơn 10% → lý do ghi
  cạnh số đo, khóa vẫn lấy mỗi lần bắn (một dấu theo giao dịch là GUC bỏ được khóa); một deadlock ngoài (e) → ghi ở
  Comments và phiên điều phối quyết thứ tự khóa.
  `Blocked by: 08, 09`: cả ba thay thân `platform.enforce_role_separation_of_duties` (ticket này dựng từ thân 09 để lại),
  (d) đo lời giải lúc commit của 08, (c) cần trigger khôi phục của 09. Không dựng cạnh ticket 10 (cùng
  `db/bench/rbac/RESULTS.md` và database đo) hay một ticket khác thêm revision Alembic. Đổi `tenant_id`, `workspace_id`
  của membership còn lần gán đã bị khóa ngoại từ chối, nên trigger mới chỉ xét `user_id`; một membership chưa có lần gán
  nào thì đổi gì cũng không mang khóa.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk một
  subagent, ranh giới 1, 2, 3, 5, 6, vì ticket có migration). `check_plans.py`: một Không đạt (mã K trong ngoặc ở tiêu
  chí đọc như mã kiểm soát thiếu ở dòng `Yêu cầu:`), sửa theo dạng của ticket 09 (`R5.1: K1, ...`). Hai HIGH, sửa ở ticket.
  (1) Tiêu chí `q2` và dòng "Nếu sai thì" cho hai câu trả lời khi số đo xấu hơn 10%, và một trong hai (dấu theo giao
  dịch) là GUC `dw_app` đặt sẵn được nên bỏ được khóa: nay một câu trả lời, khóa mỗi lần bắn, lý do ghi cạnh số đo; ADR
  và spec sửa cùng. (2) Nhánh `memberships` không nói gì khi membership không mang khóa thuộc luật mà người nhận đã vi
  phạm sẵn: nay từ chối (không trả sớm, như 09 và ADR-0104 (Accepted) mục 9), có ca ở K3. MEDIUM, sửa: K3 thêm ca hai
  tenant và đột biến (d); mốc `down_revision` của test vi sai của 08 giữ nguyên, nêu lý do; dòng Xong thêm
  `test_offboarding.py` và test của 08; tiêu chí K4 nói rõ là lớp giữ (dự đoán đúng sẵn sau 08, đỏ được bằng đột biến);
  bước 1 thêm cuộc đua (e) cho thứ tự khóa đảo (dòng version trước `FOR SHARE` trên miễn trừ): một giao dịch xác nhận
  hay thu hồi miễn trừ rồi gán vai trò, cạnh một lần gán cho người dựa vào miễn trừ đó, cho một `40P01` mới (một bên bị
  hủy, không lọt), đo riêng, và người dựng tìm nơi ghi hai thứ đó trong một giao dịch. MEDIUM, không sửa, người dựng đọc
  trước: (a) `dw_migrator` đổi `memberships.user_id` vẫn chuyển được vai trò trọng yếu sang người có dòng trong
  `platform_operators`/`support_staff` hay sang tài khoản dịch vụ, vì `guard_operator_tenant_grants` và guard tài khoản
  dịch vụ chỉ nằm trên bảng gán và bảng quyền: trái R3.11 ("kể cả `dw_migrator`"), ngoài ticket này (tách nhiệm), nợ một
  ticket của spec này, phiên điều phối cắt; Nếu sai thì: gộp vào nhánh `memberships` ở đây; (b) 23514
  `ck_roles_sod_access_version` không có ánh xạ API: chỉ xảy ra sau bước xóa của offboarding, nơi không route nào ghi
  vai trò; Nếu sai thì: API trả 409 như `ck_roles_sod_memberships`; (c) đổi `user_id` đồng thời với một lần gán không
  có ca riêng: cùng khóa ở đầu cùng hàm phủ nó.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới, cùng hai brief): 0 CRITICAL, 0 HIGH.
  MEDIUM, sửa ở thân: (1) thiếu dòng version không còn từ chối ở công ty `offboarding`/`offboarded`: ở đó lần xóa một
  người dùng làm `assigned_by` về NULL (UPDATE trên `role_assignments`, bắn trigger tách nhiệm), nên từ chối sẽ chặn xóa
  người dùng; K2 thêm ca đó và đột biến (b). (2) Nếu (d) lọt và `owner_coverage_after_write()` nhận câu khóa, thiếu dòng
  thì bỏ qua, không từ chối (trigger đó bắn cả trên DELETE của offboarding). (3) K1 thêm ca hai tenant (tenant B không
  chờ tenant A) và đột biến (d) bỏ `WHERE`, để một khóa rộng hơn không qua được test. (4) (b) của bước 1 nêu số lọt dự
  đoán (lượt lần gán đi sau), vì lần ghi quyền của vai trò đã khóa dòng version trước khi đọc qua
  `trg_tenant_role_permissions_role_version`. (5) (e): ở `0721f156` không đường nào ghi miễn trừ và vai trò trong một
  giao dịch; đường mới như thế lấy dòng version trước. (6) Dòng Xong về đúng dạng (`check_plans.py`). MEDIUM, không sửa,
  người dựng đọc trước: (a) bên bị hủy bởi `40P01` của (e) nhận lỗi không ánh xạ (500); không route nào tới được ở
  `0721f156`; Nếu sai thì: service thử lại một lần trên `40P01`. (b) Lần xóa người dùng làm `assigned_by` về NULL đã bắn
  trigger tách nhiệm hôm nay, nên xóa một người từng gán vai trò cho người đã vi phạm sẵn bị từ chối: có từ trước, không
  đổi ở đây; Nếu sai thì: trigger trên `role_assignments` chỉ bắn khi `role_id`, `membership_id` hay `expires_at` đổi,
  một ticket riêng. (c) Nợ R3.11 của MEDIUM (a) lượt trước: phiên điều phối cắt ticket (thêm vào "Danh sách ticket").
  Sửa sau lượt này không được người đọc mới đọc lại; người dựng đọc bước 2 và K1-K3 trước.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): dựng xong, `resolved`. Revision `5a68710cf15a` (trên `8ae042d86742`):
  thân `enforce_role_separation_of_duties` của ticket 09 sửa hai neo bằng `_patched()` (câu khóa dòng version
  `FOR NO KEY UPDATE` đầu thân, thiếu dòng thì 23514 `ck_roles_sod_access_version` trừ công ty `offboarding`/`offboarded`;
  nhánh `memberships`), trigger `trg_memberships_separation_of_duties`; `owner_coverage_after_write()` không đổi vì (d)
  không lọt. Số đo ở `db/bench/rbac/RESULTS.md` (mục "Đo cuộc đua tách nhiệm (tenant-rbac/11)"), harness `q6` mới trong
  `db/bench/rbac/bench_rbac.py`: trước / sau / bỏ khóa trên 200 lượt: (a) 0 / 0 / 0, (b) 106 / 0 / 109, (c) 200 / 0 / 200,
  (d) 0 / 0, (e) 0 lọt và 0 → 9 `40P01`, hai cuộc đua của Câu 3 0 / 0; không `40001`. `q2` trung vị ba lần không xấu hơn ở ô nào (gán 1.000 người một mình 14.579 → 11.660 ms, thêm 10 khóa 10 lệnh 3.957 → 3.435 ms; chênh là nhiễu của máy, số lần gọi bằng nhau).
  Khác ticket, theo số đo: (1) (a) không lọt ở commit gốc và cũng không lọt khi bỏ khóa: hai lần gán cho cùng một người
  qua `guard_operator_tenant_grants()`, hàm lấy khóa tư vấn theo người trước khi đọc, nên tiêu chí "đột biến của (a)-(c)
  lọt" chỉ đúng cho (b), (c); test K1 (a) (`test_k1a_...`) là lớp giữ, đột biến của K1 trong `mutations/11.yaml` trỏ test
  (b), (c). Nếu sai thì: một đường gán không qua guard R3.11 (không có ở head) thì (a) lọt khi bỏ khóa; test (a) vẫn giữ.
  (2) (e): 9/200 `40P01` mới, đúng như bước 1 dự đoán, 0 lọt; ở head không đường nào ghi miễn trừ rồi vai trò trong một
  giao dịch (`separation_of_duties_repo.py` chỉ ghi miễn trừ, offboarding chỉ DELETE), đường mới như thế khóa dòng version
  trước. Test: `packages/python/dw_platform/tests/integration/test_role_write_races.py`, 15 ca (K1 sáu, K2 hai, K3 sáu,
  K4 một). Gate nhanh: ruff, format, mypy (3 lỗi ở tệp của làn khác: `scripts/bench_json_schema.py`,
  `tests/support/plan_shape.py`, một test `dw_studio`; tệp của ticket sạch), integration của dòng Xong 333 xanh. Phá thử
  bằng tay cả 11 đột biến của `mutations/11.yaml`: cả 11 đỏ đúng lý do (K1 (a)-(c) bên thứ hai được nhận, (d) bên tenant
  B chờ, K2 (b) lần xóa người dùng bị từ chối, K4 không còn `owner_coverage_low_since`). `reviewing-feature-security`:
  ranh giới 1 (khóa đúng dòng của `NEW.tenant_id`, test hai tenant không chờ), 2 (mọi người ghi, `dw_migrator` cũng xét,
  test K3 dưới `dw_migrator`, K1 (a) dưới `dw_app`), 3 không áp (không đường agent), 5 (một hàm cho bốn bảng), 6 (lần đổi
  người là lối cuối của R5.1, test ở tầng database); 4 không áp (không cache). Thứ tự khóa: dòng version lấy trong trigger
  AFTER của tách nhiệm, sau khóa dòng tenant của `refuse_losing_the_last_owner` (tên `ck_` xếp trước), nên không đảo thêm.
