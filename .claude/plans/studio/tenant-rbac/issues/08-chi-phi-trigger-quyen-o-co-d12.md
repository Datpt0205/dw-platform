# 08 — Chi phí trigger quyền ở cỡ D12: kiểm chủ sở hữu mỗi giao dịch, luật giữ quyền theo neo, tách nhiệm bỏ khóa ngoài luật

Status: resolved (2026-11-06, main)
Blocked by: 02, 03, 04, 07
Area: studio
Yêu cầu: không (chi phí của ba trigger theo Phát hiện 2-4 của discovery/08; R3.12, R5.1, R6.1, R6.3, R9.5 và RB14, RB15, RB16, RB40 giữ bằng test hiện có cộng test vi sai ở đây, trừ đúng một câu trả lời đổi có chủ ý của R3.12 ở bước 1)

## Mục tiêu

discovery/08 (FOG-38) đo ở một công ty 5.000 người: gán vai trò cho 1.000 người trong một giao dịch mất 30,2 giây, 59%
là `platform.check_owner_coverage` chạy ở mỗi lệnh; thêm 10 khóa vào một vai trò 1.000 người giữ mất 15,1 giây, chia đôi
giữa luật giữ quyền xét từng lần gán của vai trò (`holder_covers_grant` 0,65 ms × 1.000 mỗi dòng) và tách nhiệm xét lại
cả 1.000 người giữ cho mỗi khóa, kể cả khóa không thuộc luật nào. Trong suốt lần ghi đó, dòng version của công ty bị khóa,
nên mọi lần ghi quyền khác của công ty chờ (Phát hiện 6, giữ nguyên theo ADR-0104 (Accepted) mục 7). Ticket này làm ba
trigger đó tốn theo số neo và số luật thay vì số lần gán, nên lần ghi lớn ngắn lại và công ty chờ ít hơn. Mọi lần ghi
được nhận hay bị từ chối như trước, với cùng ràng buộc, mã lý do và khóa thiếu; câu trả lời duy nhất đổi, có chủ ý, là
cảnh báo của một lần xuống rồi lên trong cùng một giao dịch (bước 1), không phải một lần từ chối. Test vi sai của bước 5
chứng minh điều đó.

## Việc cần làm

1. **`check_owner_coverage` một lần mỗi giao dịch** (Phát hiện 2): hôm nay 12 trigger theo câu lệnh
   `trg_<bảng>_owner_coverage_{insert,update,delete}` trên bốn bảng của `_COVERED_TABLES`
   (`db/migrations/versions/b5677d345bc1_tenant_roles.py:1031`, `:1187-1199`) gọi `platform.owner_coverage_after_write()`
   (`:1003-1027`), hàm này gọi `platform.check_owner_coverage` (thân hiện hành
   `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1038-1089`) một lần mỗi tenant mỗi
   lệnh, và mỗi lần dựng `checker_candidates` của mọi thành viên (18 ms ở 5.000 người). Thay 12 trigger đó bằng bốn trigger
   ràng buộc `AFTER INSERT OR UPDATE OR DELETE ... DEFERRABLE INITIALLY DEFERRED FOR EACH ROW`, như
   `trg_z_bump_access_version_access_mode` (`db/migrations/versions/2f177d264a27_field_access_mode.py:77`); trigger ràng
   buộc không có bảng chuyển tiếp, nên `owner_coverage_after_write()` viết lại trên `NEW`/`OLD` (UPDATE đổi `tenant_id`
   xét cả hai tenant). Một dấu theo giao dịch cho mỗi tenant (`set_config(..., true)`, tên mang id tenant) để các dòng cùng
   tenant chạy `check_owner_coverage` một lần mỗi điểm bắn; thân `check_owner_coverage` không đổi. Dấu ghi một giá trị mà
   mọi lệnh ghi sau làm cũ, không ghi "đã xét": `version` của `platform.tenant_access_versions` đọc ngay sau lần kiểm (lần kiểm tự ghi `platform.tenants`, một bảng tăng
   version) là một cách, vì
   cả bốn bảng nằm trong `_BUMPED_TABLES` (`b5677d345bc1_tenant_roles.py:759-767`), nên dòng nào bắn khi version đã khác
   dấu thì kiểm lại. Vì vậy sau `SET CONSTRAINTS ALL IMMEDIATE` (hôm nay không ai trong repo gọi), khi trigger bắn ở cuối
   mỗi lệnh, mỗi lệnh có ghi được kiểm một lần, đúng như trigger theo câu lệnh hôm nay; `ROLLBACK TO SAVEPOINT` lùi cả dấu
   lẫn version. Dấu thiếu, cũ hay không đọc được thì kiểm (fail closed); hết cùng giao dịch, nên không sót qua kết nối
   của pool. Hàm vẫn SECURITY DEFINER và lọc theo `tenant_id` của dòng, nên kết quả không phụ thuộc `app.tenant_id` lúc
   commit. Sự kiện
   `platform.tenant.owner_coverage_low` và cột `owner_coverage_low_since` vẫn ghi trong chính giao dịch đó (R3.12, RB40).
   **Câu trả lời đổi duy nhất, có chủ ý** (agent, theo ủy quyền 31/10/2026; ghi ở "Quyết định" của spec, R3.12): lần
   kiểm đọc trạng thái lúc commit. Một
   giao dịch nhiều lệnh đưa số người giữ xuống dưới hai rồi lên lại (thay người quản trị: gỡ người thứ hai rồi gán người
   mới) hôm nay ghi một sự kiện dù cột về NULL trước commit; sau ticket thì không có sự kiện nào, vì không giao dịch nào
   khác từng thấy lần xuống đó. Lên rồi xuống trong một giao dịch vẫn một sự kiện. "Một lần mỗi lần xuống" của R3.12 đọc
   theo trạng thái đã commit. Nếu sai thì: giữ trigger theo câu lệnh và chỉ làm `check_owner_coverage` rẻ hơn (đếm tới
   hai người rồi dừng), đo lại.
   Không đổi: luật chủ sở hữu cuối `ck_role_assignments_last_owner`
   (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:871-927`, `:1126-1131`), trigger từ
   chối duy nhất về chủ sở hữu, giữ theo dòng và ngay lúc lệnh; `check_owner_coverage` không từ chối lần ghi nào, chỉ
   cảnh báo. Test đang đọc cột hay outbox trong chính giao dịch ghi
   (`packages/python/dw_platform/tests/integration/test_tenant_roles.py:1186-1192`) chuyển lần đọc ra sau commit: trước
   commit lần kiểm hoãn chưa chạy, nên test đó không còn đỏ được (failure-modes #3).
2. **Luật giữ quyền theo neo** (Phát hiện 3): thân hiện hành của `platform.rbac_refusals` là
   `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:387-409`: thân của
   `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:340-466` cộng nhánh `obj.*`/`fld.*`
   không cấp được của ticket 04. Revision mới dựng từ thân đó, nạp bằng `_earlier()` và sửa bằng `_patched()` (neo phải
   khớp đúng một lần, `ef68083f2905_object_and_field_privileges_in_roles.py:73-100`), không chép tay thân của
   `d2b57239ef50`; downgrade dựng lại đúng thân `ef68083f2905` đó. Chỉ nhánh có gán của CASE trong op `add`, `raise`,
   `remove`, `lower` (`d2b57239ef50_role_administration_and_anti_escalation.py:399-433`) đổi: `holder_covers_grant` xét
   trên `SELECT DISTINCT a.workspace_id` của vai trò (≤ số workspace), như op `role_delete` đã làm (`:450-463`), thay vì
   từng lần gán; và trước đó một lời gọi `platform.holder_covers_grant(..., NULL)` (neo NULL chỉ đúng khi người làm giữ
   khóa ở mức `tenant`, và khi đó hàm đúng ở mọi neo) đúng thì không từ chối, không xét neo nào. Phép tắt là chính hàm đó,
   không một câu đọc `effective_grants` thứ hai. Op này trả tối đa một dòng như trước, nên `HINT` không đổi. Bằng nhau vì `platform.holder_covers_grant`
   (`db/migrations/versions/557e6907195e_service_principals_run_as.py:464-479`) chỉ phụ thuộc tenant, người làm, khóa, độ
   sâu và neo, không phụ thuộc lần gán. Luật vẫn là hàm đó, không chép sang chỗ khác. Giữ nguyên: khối `p_lock` lấy
   `FOR SHARE` các gán của người làm ở đầu hàm (ADR-0104 (Accepted) mục 6; discovery/08 Câu 3: 0/200 lần lọt), nhánh
   ELSE của vai trò chưa ai giữ (người làm giữ khóa ở mức bằng hay rộng hơn ở một neo bất kỳ), op `grant`, `revoke` và
   các op `role_*`. Lần ghi quyền object và quyền trường (`rbac_guard` của ticket 04,
   `ef68083f2905_object_and_field_privileges_in_roles.py:417-521`, sinh op `add`, `remove`) đi qua cùng nhánh nên cũng rẻ
   đi.
3. **Tách nhiệm bỏ qua khóa ngoài luật** (Phát hiện 4): trên `platform.tenant_role_permissions`,
   `platform.enforce_role_separation_of_duties` (`db/migrations/versions/b5677d345bc1_tenant_roles.py:584-628`) xét lại
   mọi người giữ vai trò cho mỗi dòng bằng `platform.sod_violation`, mỗi người một lời gọi. Một dòng có
   `NEW.permission_key` không nằm ở `left_scopes` hay `right_scopes` của luật nào không làm ai giữ thêm một vế, nên sau
   lần ghi một người vi phạm khi và chỉ khi người đó đã vi phạm trước. Nhưng trigger hôm nay vẫn từ chối dòng đó khi một
   người giữ đã vi phạm sẵn, và ADR-0104 (Accepted) mục 9 viết đúng như vậy ("refuse a change leaving any holder in
   breach"): vi phạm có sẵn xảy ra được (khôi phục vai trò đã xóa mềm không qua trigger tách nhiệm, vốn chỉ có trên hai
   bảng, `b5677d345bc1_tenant_roles.py:1161-1166`; một luật mới thêm bằng migration). Nên không trả sớm vô điều kiện:
   với khóa ngoài luật, một câu theo tập hỏi "có người giữ nào của vai trò đang giữ cả hai vế của một luật không"
   (qua `platform.assigned_grants` và `platform.sod_rule_broken`, `b5677d345bc1_tenant_roles.py:531-541`, không phép
   khớp thứ hai, bỏ qua miễn trừ), trên đúng tập người của `v_people` ở đường cũ (`:601-606`, mọi gán của vai trò, kể cả
   gán đã hết hạn) và đúng tập khóa của `platform.sod_held_keys` (`:522-528`); không ai thì trả mà không gọi `sod_violation`; có thì chạy đúng đường cũ, nên cùng
   từ chối, cùng `DETAIL`, `HINT` và cùng `FOR SHARE` trên miễn trừ. Bỏ qua miễn trừ ở câu hỏi đó chỉ làm đường cũ chạy
   thêm, không bao giờ bỏ một lần từ chối. "Thuộc luật" đọc `platform.sod_rules` lúc chạy, cùng phép bằng như
   `sod_rule_broken` (khóa là một phần tử của mảng); UPDATE chỉ xét `NEW`. Khóa thuộc luật và dòng `role_assignments`
   giữ đường cũ. Không câu trả lời nào đổi ở bước này.
4. Một revision (id hex của `alembic revision`): `CREATE OR REPLACE` ba hàm `platform.owner_coverage_after_write()`,
   `platform.rbac_refusals(uuid, uuid, jsonb, boolean)` và `platform.enforce_role_separation_of_duties()` (thay thân
   như vậy giữ quyền EXECUTE; một hàm mới, nếu có, REVOKE khỏi PUBLIC và vào danh sách SECURITY DEFINER của
   `packages/python/dw_platform/tests/integration/test_privileges.py:1850-1861`), DROP 12 trigger theo câu lệnh và
   CREATE bốn trigger ràng buộc của bước 1. Downgrade dựng lại thân `b5677d345bc1` của `owner_coverage_after_write` và
   của tách nhiệm, 12 trigger theo câu lệnh và thân `ef68083f2905` của `rbac_refusals`. Không bảng, quyền vai hay bước
   offboarding mới, nên `test_rls_coverage.py` và `test_offboarding_coverage.py` không đổi.
5. **Test vi sai qua migration** (integration, `packages/python/dw_platform/tests/integration/`): hai database của
   làn, một nâng tới `down_revision` của revision này (`alembic upgrade <down_revision>`), một tới head, không hạ
   database nào xuống, nên một revision khác nằm trên không bị chạm; cả hai xóa sau test. Một tập lần ghi cố định chạy
   trên cả hai; mỗi lần ghi trên một tenant gieo mới dưới `dw_migrator` (cùng hàm gieo, cùng tham số ở cả hai database),
   nên không lần ghi nào thấy dư của lần trước, rồi ghi trong giao dịch riêng dưới `dw_app` như service ghi
   (`app.tenant_id`, `app.user_id`, đề xuất xác nhận trong chính giao dịch khi lần ghi nới). Mỗi lần ghi cho một dòng kết
   quả: nhận, hay SQLSTATE cộng tên ràng buộc cộng `DETAIL` (mã lý do) cộng `HINT` (khóa thiếu); nhóm chủ sở hữu thêm
   `owner_coverage_low_since` và số sự kiện `platform.tenant.owner_coverage_low` đọc sau commit. Hai danh sách bằng nhau
   từng dòng, trừ đúng dòng "xuống rồi lên trong một giao dịch" (bước 1), mà test khẳng định riêng ở cả hai database.
   Tập lần ghi theo dạng của bench ở cỡ nhỏ (vài chục thành viên, ba workspace): op `add`, `raise`, `remove`, `lower`;
   người làm giữ khóa ở mức `workspace` tại A, tại A và B, ở mức `tenant`, không giữ ở đâu; vai trò chưa ai giữ, gán ở một
   neo, ở hai neo; khóa nền tảng, `obj.*` (cả mức `own`: người làm giữ `own` ở A, vai trò gán ở B), `fld.*`; khóa vế trái, vế phải, ngoài luật, luật miễn trừ được có và không có
   miễn trừ đã xác nhận, vai trò có người vi phạm sẵn; gán qua `platform.roles.bind` và không; công ty xuống dưới hai,
   lên lại, hai tenant trong một giao dịch, xuống rồi lên trong một giao dịch, lên rồi xuống trong một giao dịch, lần ghi
   sau `SET CONSTRAINTS ALL IMMEDIATE`, lần ghi sau `ROLLBACK TO SAVEPOINT`. Rồi đo lại `q2` của `make bench-rbac`.

Kiểm soát của ticket này (mã K chỉ dùng trong ticket; mỗi dòng một đột biến khi dựng):

| #   | Kiểm soát                                                | Test âm                                                                                                                                                                                                                                                                                                          |
| --- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | Cảnh báo dưới hai người vẫn đúng một lần, cùng giao dịch | Gỡ gán của người giữ thứ hai `platform.roles.write` → đúng một sự kiện `platform.tenant.owner_coverage_low`; sai nếu dấu theo giao dịch bỏ qua tenant thứ hai cùng giao dịch, lần ghi sau `SET CONSTRAINTS ALL IMMEDIATE` hay lần gỡ sau commit → test đỏ                                                        |
| K2  | Luật giữ quyền theo neo từ chối đúng lần ghi cũ          | Người làm giữ khóa ở `workspace` A, vai trò gán ở A và B, thêm khóa → `rbac_refusals_tenant_role_permissions`; vai trò chưa ai giữ, người làm không giữ khóa ở đâu → cùng ràng buộc; sai nếu chỉ xét một neo hay tập neo rỗng được nhận → test đỏ                                                                |
| K3  | Tách nhiệm vẫn từ chối mọi lần ghi nó từ chối hôm nay    | Thêm khóa vế phải vào vai trò mà một người giữ vế trái → 23514 `ck_roles_sod_memberships`; thêm khóa ngoài luật vào vai trò có người vi phạm sẵn (vai trò khôi phục dưới `dw_migrator`) → cùng ràng buộc; sai nếu phép trả sớm đọc nhầm vế, bỏ luật miễn trừ được hay trả sớm khi có người vi phạm sẵn → test đỏ |

## Tiêu chí chấp nhận

- [x] K1: test cảnh báo một lần mỗi lần xuống xanh với hai tenant trong một giao dịch và với lần ghi sau
      `SET CONSTRAINTS ALL IMMEDIATE`; sai nếu thiếu hay thừa một sự kiện, và đột biến của K1 làm test đỏ.
- [x] K2: test hai neo và test vai trò chưa ai giữ xanh; sai nếu một trong hai lần ghi đó được nhận, và đột biến của K2
      làm test đỏ.
- [x] K3: test vế phải và test vi phạm sẵn xanh; sai nếu một trong hai lần ghi đó được nhận, và đột biến của K3 làm test
      đỏ.
- [x] Vi sai (bước 5): hai danh sách kết quả bằng nhau từng dòng; sai nếu một lần ghi của tập cho kết quả khác giữa hai
      database (nhận hay từ chối, ràng buộc, mã lý do, khóa thiếu, cột, số sự kiện) ngoài dòng "xuống rồi lên trong một
      giao dịch" của bước 1, hay nếu dòng đó không đổi đúng như bước 1 ghi (một sự kiện trước, không sự kiện nào sau).
- [x] Số đo: `q2` của `make bench-rbac` trước (bản `git archive` của commit ngay trước commit đầu của ticket này) và sau,
      cùng máy, ở `RESULTS.md` và Comments: lần gán 1.000 người, "thêm 10 khóa, 10 lệnh", "bỏ 10 khóa", "thêm 5 quyền
      object", trung vị ba lần chạy mỗi bên, mỗi lần kèm số lần gọi từ `pg_stat_xact_user_functions` (bench đặt
      `track_functions = 'all'`, `db/bench/rbac/bench_rbac.py:516`; `check_owner_coverage` và `holder_covers_grant` đếm 0 là
      "không đo được", không phải đạt). Sau sửa:
      `check_owner_coverage` một lần mỗi tenant mỗi giao dịch (trước 1.000 ở lần gán), `holder_covers_grant` mỗi dòng
      quyền không quá số workspace riêng của vai trò cộng một, và đúng một khi người làm giữ khóa ở mức `tenant` (trước
      1.000), `sod_violation` 0 cho khóa ngoài luật khi không người giữ nào vi phạm sẵn (trước 1.000 mỗi dòng); sai nếu
      một số lần gọi vượt mức đó hay trung vị thời gian của lần ghi không giảm.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `db/migrations/versions/b5677d345bc1_tenant_roles.py:1003-1027` (`owner_coverage_after_write`), `db/migrations/versions/b5677d345bc1_tenant_roles.py:1187-1199` (12 trigger theo câu lệnh), `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1038-1089` (`check_owner_coverage`), `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:871-927` (chủ sở hữu cuối, không đổi), `db/migrations/versions/2f177d264a27_field_access_mode.py:77`; spec: R3.12, RB40.
- `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:387-409` (thân hiện hành của `rbac_refusals`), `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:399-433`, `db/migrations/versions/557e6907195e_service_principals_run_as.py:464-479`; spec: R6.1, R6.3, R9.5, RB15, RB16; ADR-0104 (Accepted) mục 6.
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:531-541` (`sod_rule_broken`), `db/migrations/versions/b5677d345bc1_tenant_roles.py:584-628`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:1161-1166`; spec: R5.1, RB14.
- `db/bench/rbac/RESULTS.md:104-166` (Câu 2), `db/bench/rbac/RESULTS.md:239-254` (Phát hiện 2-4, 6).

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cắt từ Phát hiện 2-4 của discovery/08 cùng lúc với ticket 07, để ba
  việc cần migration không mất; chưa gate. Chờ ticket 07 vì cùng harness và cùng mốc đo (`gc.freeze()` bỏ nhiễu GC khỏi
  số `/me` cạnh lần ghi). Nếu sai thì: tách thành ba ticket, mỗi trigger một.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): từ gate của ticket 07 (MEDIUM (i)): `_STANDING`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:511-521`) và `_HOLDERS`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:29-40`) gọi `platform.scopes_in`
  trong danh sách SELECT như `_HELD` trước ticket 07, không nằm trên đường `/me`, chưa đo. Gate ticket này quyết đưa vào
  đây (không migration) hay tách ticket. Nếu sai thì: một ticket riêng không migration, cùng test bằng nhau của ticket 07.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, ranh giới
  1, 2, 3, 5, 6, vì ticket có migration), script 24 Đạt; đọc thân hàm ở head. Năm HIGH, sửa ở ticket. (1) Thân gốc và
  thân downgrade của `rbac_refusals` không được nêu: thân ở head là của `ef68083f2905` (nhánh `obj.*`/`fld.*` của ticket
  04), chép thân `d2b57239ef50` mà ticket dẫn sẽ mất R9.5 lặng lẽ; nay dựng bằng `_earlier()`/`_patched()` từ thân
  `ef68083f2905`, giữ `p_lock` và nhánh vai trò chưa ai giữ, và bước 4 nêu đúng ba hàm, 12 trigger bỏ, bốn trigger ràng
  buộc thêm, cái downgrade dựng lại. (2) "Không đổi câu trả lời nào" sai ở bước 1: xuống rồi lên trong một giao dịch hôm
  nay ghi một sự kiện, kiểm lúc commit thì không; nay là câu trả lời đổi thứ nhất, ghi ở bước 1. `check_owner_coverage`
  không từ chối gì; luật chủ sở hữu cuối là `ck_role_assignments_last_owner`, ticket không đổi. (3) Cũng sai ở bước 3:
  trigger tách nhiệm hôm nay từ chối mọi khóa thêm vào vai trò có người vi phạm sẵn (khôi phục vai trò không qua tách
  nhiệm), phép trả sớm vô điều kiện thì nhận (sửa lại ở lượt xác nhận, dòng dưới). (4) Phép chứng minh bằng nhau không
  có cách chạy "trước" và không có tiêu chí: nay là test vi sai trên hai database (một ở `down_revision`, một ở head),
  trên tập lần ghi theo dạng bench, so từng dòng kết quả, có tiêu chí riêng. (5) "Sai nếu không giảm" đỏ được vì nhiễu:
  nay kèm số lần gọi từ `pg_stat_xact_user_functions`, mỗi hàm một mức, và trung vị ba lần. Nếu sai thì: (1) migration
  hỏng vì neo `_patched` không khớp, lộ ra khi dựng; (2) giữ trigger theo câu lệnh như bước 1 ghi; (3) xem dòng dưới;
  (4) `alembic downgrade` một bước rồi `upgrade` trên một database; (5) chỉ so thời gian.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (người đọc mới, cùng hai brief). CRITICAL, sửa,
  không chấp nhận: câu trả lời đổi thứ hai của lượt đầu (nhận khóa ngoài luật vào vai trò có người vi phạm sẵn) trái
  ADR-0104 (Accepted) mục 9 ("refuse a change leaving any holder in breach"); bước 3 nay không trả sớm vô điều kiện mà hỏi
  một câu theo tập có người giữ nào đang vi phạm, không ai thì bỏ vòng `sod_violation`, có thì chạy đường cũ, nên không
  câu trả lời nào đổi ở bước 3; K3 thêm ca vi phạm sẵn. HIGH, sửa: dấu "đã xét" theo giao dịch làm im mọi lệnh ghi sau
  `SET CONSTRAINTS ALL IMMEDIATE` (trigger bắn cuối mỗi lệnh); dấu nay ghi một giá trị lệnh ghi sau làm cũ (`version`
  đọc sau lần kiểm), mỗi lệnh có ghi được kiểm như hôm nay, cùng ca `ROLLBACK TO SAVEPOINT`. MEDIUM, sửa: phép tắt mức
  `tenant` của bước 2 là `holder_covers_grant(..., NULL)`, không bản sao thứ hai của luật giữ quyền; câu trả lời đổi của
  R3.12 ghi ở "Quyết định" của spec; test vi sai không hạ database nào, gieo tenant mới mỗi lần ghi. Sửa sau lượt xác nhận
  không được người đọc mới đọc lại (gate cho tối đa hai lượt); người dựng đọc bước 1 và 3 trước. Nếu sai thì: CRITICAL:
  sửa ADR-0104 (Accepted) mục 9 bằng một Amendment trước khi đổi câu trả lời; HIGH: trigger theo câu lệnh như cũ; lỗi khác lộ ra
  khi dựng, ghi ở Comments.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): `_STANDING` và `_HOLDERS` không vào ticket này: là code, không migration,
  không nằm trên đường của ba trigger, và chưa ai đo. `_HOLDERS` gọi `scopes_in` cho mỗi thành viên của một workspace,
  nên ở 5.000 người có thể tốn hơn `_HELD` nhiều lần. Nợ một ticket riêng của spec này, không migration: đo hai câu ở cỡ
  D12 trước, chuyển `scopes_in` vào FROM nếu số đo cho thấy cần, cùng test bằng nhau của ticket 07. Phiên điều phối cắt
  ticket đó (`/to-tickets`, thêm vào "Danh sách ticket"). Nếu sai thì: thêm hai câu vào đây thành bước 6, cùng test.
- 2026-11-05 (agent): gate, MEDIUM, không sửa, người dựng đọc trước. (a) Dấu theo giao dịch là GUC, nên SQL thô dưới
  `dw_app` đặt sẵn được và bỏ được một lần cảnh báo (không bỏ được lần từ chối nào): nhận rủi ro (agent, theo ủy quyền
  31/10/2026), vì cảnh báo không phải cửa phân quyền và mọi luật từ chối vẫn chạy; Nếu sai thì: dấu trong một bảng tạm
  chỉ hàm SECURITY DEFINER ghi. Dấu là `version` thì muốn bỏ lần kiểm phải đặt đúng version, vẫn đặt được. (b) Hai giao dịch đồng thời, mỗi giao dịch gỡ một trong ba người giữ, có thể cùng đếm
  thấy hai và không ai cảnh báo; có từ trước (theo câu lệnh cũng vậy), kiểm lúc commit thu hẹp cửa sổ; chủ là R3.12,
  không sửa ở đây. (c) HIGH ngoài ticket này, không chặn nó: khôi phục vai trò đã xóa mềm (`tenant_roles.deleted_at` về
  NULL) trả mọi khóa cho người giữ mà không qua trigger tách nhiệm (chỉ có trên `role_assignments` và
  `tenant_role_permissions`, `b5677d345bc1_tenant_roles.py:1161-1166`), nên một người giữ cả hai vế mà không ai từ chối,
  trái R5.1 và ADR-0104 (Accepted) mục 9; nợ một ticket của spec này (trigger tách nhiệm cho lần khôi phục, có migration),
  phiên điều phối cắt. Ticket này không dựa vào kẽ hở đó.
  (d) Lỗi của `check_owner_coverage` (ghi outbox) nay ra ở COMMIT, không ở lệnh: API thấy lỗi lúc commit, như các trigger
  hoãn hiện có. (e) `holder_covers_grant` là hàm SQL: nếu bản viết lại làm nó được inline thì `pg_stat_xact_user_functions`
  đếm 0 mà chi phí vẫn còn; tiêu chí thời gian giữ chỗ đó. (f) Đừng dựng cạnh một ticket cũng thêm revision Alembic
  (usage-and-limits/03 đang ở lane 1, tenant-rbac/06) hay sửa `test_tenant_roles.py` (tenant-rbac/06).
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): lượt xác nhận thứ hai (mức tối đa của gate): 0 CRITICAL, 0 HIGH. MEDIUM,
  sửa ở thân: câu hỏi theo tập của bước 3 dùng đúng tập người `v_people` và tập khóa `sod_held_keys` của đường cũ; tập
  vi sai có ca `obj.*` mức `own` cho phép tắt `holder_covers_grant(..., NULL)` (neo NULL không khớp neo nào, chỉ mức
  `tenant` qua); tiêu chí số đo nêu `track_functions = 'all'` của bench và số đếm 0 không tính là đạt. MEDIUM, không
  sửa, người dựng quyết: (g) ADR-0104 (Accepted) mục 10 viết "once each time ... fall below two" không nói giao dịch;
  cách đọc theo trạng thái đã commit ghi ở "Quyết định" của spec, khuyến nghị một dòng Amendments khi phiên điều phối
  sửa ADR (gate này không sửa ADR); (h) test vi sai ở lại trong bộ integration làm lớp chống hồi quy: một revision sau đổi
  một trong ba hàm thì đổi `down_revision` mốc của test cùng commit đó, và hai database mang hậu tố của làn,
  `DROP ... IF EXISTS` trước khi tạo; (i) id gieo tất định ở cả hai database, `owner_coverage_low_since` so là NULL hay
  không, không so thời điểm; (j) lần chuyển `setup` → `active` (R3.10) là `complete_tenant_setup`, trigger riêng, không
  đổi. Sửa sau lượt này không được người đọc mới đọc lại; người dựng đọc bước 1-3 và các MEDIUM trước. Nếu sai thì: lỗi
  lộ ra khi dựng, ghi ở Comments.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): dựng xong, `resolved`. Revision `a7ca12c36ec7` (trên `fece6611d786`)
  thay ba thân hàm bằng `_earlier()`/`_patched()` (thân `rbac_refusals` của `ef68083f2905`), bỏ 12 trigger theo câu lệnh,
  thêm bốn trigger ràng buộc `trg_<bảng>_owner_coverage`; tập anchor của bước 2 là CTE `MATERIALIZED` (không thì hàm
  STABLE bị đẩy xuống dưới DISTINCT và lại chạy mỗi lần gán, đo được). Khác ticket: (1) `db/migrations/env.py` đặt
  `SET CONSTRAINTS ALL IMMEDIATE` cho lần chạy migration: mọi revision chung một giao dịch, nên sự kiện hoãn của một
  backfill làm `ALTER TABLE` sau đó của cùng bảng hỏng ("pending trigger events"), chỉ trên database có dữ liệu; test
  `test_a_revision_may_alter_a_role_table_a_backfill_wrote_on_a_populated_database` giữ. Hai test sửa `ALTER TABLE` sau
  lần ghi (`test_privileges.py`, `test_service_principals_db.py`) cũng bắn sự kiện hoãn trước. (2) Harness bench bắn
  trigger hoãn bằng `SET CONSTRAINTS ALL IMMEDIATE` trước khi đọc bộ đếm và luôn liệt kê ba hàm đếm (0 là "không gọi").
  (3) Test của bước 5 và K1-K3: `packages/python/dw_platform/tests/integration/test_role_trigger_cost_db.py` (hai
  database `dw_test_trbac08_before`/`_after` mang hậu tố làn). (4) Hai test của `test_tenant_roles.py` đỏ vì
  agent-lifecycle/04 (`0353c313569f`) đăng ký `studio.publish.approve` (khóa `workspace`): giả định "chỉ khóa của ticket
  03 có trong danh mục" và "khóa chủ là khóa `tenant`" sai. `test_the_guard_and_the_coverage_name_the_same_two_keys` bỏ
  phép khẳng định loại khóa (guard và lần đếm không đọc độ sâu, loại khóa là của danh mục);
  `test_no_warning_while_an_owner_key_is_not_in_the_catalogue` dựng ca thay vì giả định: một giao dịch rút mọi khóa chủ
  trừ khóa đầu khỏi danh mục, gỡ, bắn lần kiểm hoãn, đọc, rồi ROLLBACK; phá thử (đếm khóa chủ không qua danh mục) đỏ.
  `apps/worker/tests/integration/test_owner_coverage_db.py` đọc khóa chủ có trong danh mục rồi chỉ đăng ký khóa thiếu
  (hết lỗi setup), đọc sau commit. Số đo `q2` (trước `0721f156`, sau `cce36795` cộng tệp ticket, trung vị ba lần, ms):
  gán 1.000 người một mình 41.268 → 21.016, thêm 10 khóa 10 lệnh 20.089 → 5.804, bỏ 10 khóa 9.876 → 501, thêm 5 quyền
  object 5.093 → 698; `check_owner_coverage` 1.000 → 1 mỗi giao dịch, `holder_covers_grant` 10.000 → 10 (người làm ở
  mức `tenant`: một lần mỗi dòng), `sod_violation` 10.000 → 0 cho khóa ngoài luật; bảng ở `db/bench/rbac/RESULTS.md`
  (mục "Đo lại sau tenant-rbac/08"). Gate nhanh: ruff, format, mypy (962 tệp; 951 trong container 3.12.16), unit
  `dw_platform` + worker 531 xanh, integration của ticket và ba test migration 202 + 42 xanh; unit trên bản xuất sạch
  trong `python:3.12-slim-bookworm` đỏ đúng các test cần `.git`, uid 0 hay rlimit của máy (docgen, release manifest,
  compose policy, retention manifest, CEL memory bomb), như lần chạy trước ticket. `reviewing-feature-security`: ranh giới
  1 (hàm SECURITY DEFINER lọc theo `tenant_id` của dòng, dấu mang id tenant, test hai tenant trong một giao dịch), 2 (mọi
  lần từ chối giữ nguyên, test vi sai), 5 (cùng hàm cho mọi người ghi, `dw_migrator` cũng qua trigger), 6 (dấu hết cùng
  giao dịch, test cùng kết nối sau commit); 3 và 4 không áp (không đường agent, không cache). `mutations/08.yaml` 16 đột
  biến, chạy lúc đóng hàng đợi; phá thử bằng tay K3 (phép trả sớm bỏ qua người vi phạm sẵn): 3/4 ca K3 đỏ. Chưa:
  `make test-integration` cả bộ (lúc đóng hàng đợi, wave-close.md).
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): từ gate ticket 12 (`cce36795`): lần kiểm hoãn ghi `platform.tenants`
  (cột `owner_coverage_low_since`, chỉ khi xuống dưới hai hay lên lại) sau khi giao dịch đã giữ dòng
  `platform.tenant_access_versions` (khóa ở chính lệnh ghi, `trg_z_bump_access_version`), còn
  `refuse_losing_the_last_owner` lấy dòng tenant rồi dòng version, nên cạnh một lần đổi chủ sở hữu cuối hai giao dịch có
  thể `40P01`: một bên bị hủy, không lọt (fail closed). Không sửa ở đây: dòng version đã khóa từ lệnh ghi, trước khi
  trigger hoãn chạy, nên khóa dòng tenant đầu trigger không đổi thứ tự; thứ tự này cũng có trước ticket (trigger theo câu
  lệnh bắn sau các trigger theo dòng của chính lệnh, `trg_z_bump_access_version` đã khóa dòng version). Tham chiếu: bước 1
  của ticket 12. Nếu sai thì: lần ghi lấy dòng tenant (`FOR NO KEY UPDATE`) trước dòng version ở đầu mọi lệnh ghi bốn
  bảng, đo bằng cuộc đua của ticket 11.
