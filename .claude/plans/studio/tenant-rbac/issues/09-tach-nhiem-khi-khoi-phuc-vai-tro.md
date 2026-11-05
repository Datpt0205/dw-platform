# 09 — Tách nhiệm khi khôi phục vai trò đã xóa mềm, và luật tách nhiệm không nêu khóa sinh

Status: ready-for-agent
Blocked by: 08
Area: studio
Yêu cầu: R5.1, RB14

## Mục tiêu

R5.1 và RB14: không ai giữ khóa của cả hai vế một luật tách nhiệm chưa có miễn trừ đã xác nhận. Hôm nay hai trigger tách
nhiệm chỉ nằm trên `platform.role_assignments` và `platform.tenant_role_permissions`
(`db/migrations/versions/b5677d345bc1_tenant_roles.py:1161-1166`), còn khóa của vai trò đã xóa mềm không tính
(`platform.assigned_grants` lọc `r.deleted_at IS NULL`,
`db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:301-318`). Nên một người được gán vai trò
vế phải, vai trò bị xóa mềm, người đó nhận vai trò vế trái (trigger không thấy vế phải), rồi vai trò được khôi phục
(`deleted_at` về NULL): người đó giữ cả hai vế mà không lần ghi nào bị từ chối, trái R5.1 và ADR-0104 (Accepted) mục 9
("refuse a change leaving any holder in breach"). Hôm nay chỉ `dw_migrator` khôi phục được (dưới `dw_app` lần khôi phục là
lần nới và không loại đề xuất nào khớp nó, nên `rbac_two_people` từ chối, xem đầu "Việc cần làm"), nên đây là tầng cuối
thiếu (failure-modes #5), và mọi đường khôi phục sau này (một loại đề xuất mới theo quyết định D11 của spec) thừa hưởng
kẽ hở. Ticket này cho lần khôi phục đi qua đúng hàm tách nhiệm, và chặn đường thứ hai cùng dạng: luật tách nhiệm nêu
một khóa sinh `obj.*`/`fld.*`, vốn đến từ hai bảng quyền của ticket 04 không có trigger tách nhiệm.

## Việc cần làm

Đã kiểm ở `657ef4c6` (5/11/2026):

- Lần khôi phục được `platform.rbac_guard` xếp là nới với op `role_restore` và không `v_kind`
  (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:548-550`); khối hai người
  (`d2b57239ef50_role_administration_and_anti_escalation.py:654-702`) chỉ khớp `v_kind` của bốn loại đề xuất
  (`d2b57239ef50_role_administration_and_anti_escalation.py:94-95`), nên dưới `dw_app`, `dw_admin` hay `dw_provisioner`
  lần khôi phục luôn bị từ chối trước khi tới trigger AFTER. `dw_migrator` được miễn cả hàm
  (`d2b57239ef50_role_administration_and_anti_escalation.py:513-515`). Luật giữ quyền vẫn xét lần khôi phục
  (`d2b57239ef50_role_administration_and_anti_escalation.py:450-463`, thân hiện hành dựng từ đó ở
  `ef68083f2905_object_and_field_privileges_in_roles.py:387-409`). Ticket này không đổi `rbac_guard` hay `rbac_refusals`.
- Hàm tách nhiệm `platform.enforce_role_separation_of_duties` (`b5677d345bc1_tenant_roles.py:584-628`, thân ticket 08 viết
  lại ở bước 3 của nó) không miễn người ghi nào, nên `dw_migrator` cũng bị xét khi gán.
- Tiền lệ cùng dạng: guard tài khoản dịch vụ đã xét lần khôi phục, cho mọi người ghi
  (`db/migrations/versions/557e6907195e_service_principals_run_as.py:348-351`, trigger
  `BEFORE UPDATE OF deleted_at ON platform.tenant_roles` ở `557e6907195e_service_principals_run_as.py:444-446`), và test
  của nó khôi phục dưới chủ bảng (`packages/python/dw_platform/tests/integration/test_service_principals_db.py:348-371`).
- `platform.sod_rules` chỉ `dw_migrator` ghi (`db/migrations/versions/b9862fa13a80_platform_separation_of_duty_rules_guard_.py:53-79`),
  không ràng buộc nào về khóa trong `left_scopes`/`right_scopes`; ở head không migration nào gieo luật. `sod_held_keys`
  (`b5677d345bc1_tenant_roles.py:522-528`) đọc `assigned_grants`, nên gồm cả khóa `obj.*`/`fld.*` của
  `platform.tenant_role_object_privileges` và `studio.field_permissions`, hai bảng không có trigger tách nhiệm.

Việc:

1. **Trigger tách nhiệm cho lần khôi phục.** Một revision (id hex của `alembic revision`) thêm
   `CREATE TRIGGER trg_tenant_roles_separation_of_duties AFTER UPDATE OF deleted_at ON platform.tenant_roles FOR EACH ROW
WHEN (OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL) EXECUTE FUNCTION platform.enforce_role_separation_of_duties()`,
   AFTER theo dòng, không hoãn, như hai trigger hiện có. `CREATE OR REPLACE` hàm đó với một nhánh
   `TG_TABLE_NAME = 'tenant_roles'`: `v_people` là mọi người có một lần gán vai trò `NEW.id` trong `NEW.tenant_id` (cùng
   tập như nhánh quyền của vai trò, kể cả gán đã hết hạn), không phép trả sớm nào của ticket 08 (lần khôi phục trả mọi
   khóa của vai trò), rồi cùng phần xét chung với `NEW.tenant_id`, nên cùng SQLSTATE 23514, ràng buộc
   `ck_roles_sod_memberships`, `HINT` (luật) và `DETAIL` (tối đa 20 người) như R5.1. Vì không trả sớm, khôi phục một vai
   trò mà một người giữ nó đã vi phạm sẵn cũng bị từ chối, dù vai trò chỉ mang khóa ngoài luật: đúng như nhánh quyền của
   vai trò ticket 08 giữ (ADR-0104 (Accepted) mục 9). Xóa mềm (chỉ siết) không qua trigger này, kể cả khi có người vi
   phạm sẵn. Nhánh mới không đọc `NEW.role_id`, `NEW.membership_id` hay `NEW.permission_key` (bảng `tenant_roles` không
   có, plpgsql lỗi lúc chạy). Thân dựng từ thân ticket 08 để lại, nạp bằng `_earlier()` và sửa bằng `_patched()` (neo
   khớp đúng một lần, `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100`), không chép
   tay; downgrade dựng lại đúng thân đó và DROP trigger mới. Không xét người ghi: `dw_migrator` cũng bị từ chối, như guard
   tài khoản dịch vụ. Hai giao dịch đồng thời (khôi phục R, và gán L cho cùng người) cùng qua được, vì mỗi bên xét trước
   khi khóa dòng version (`trg_z_bump_access_version` bắn sau cùng; đọc từ thứ tự trigger, chưa đo): cùng cửa sổ như
   hai lần gán đồng thời hôm nay, không sửa ở đây (Comments: rủi ro nhận theo ủy quyền, và chủ của nó).
2. **Luật tách nhiệm không nêu khóa sinh.** Cùng revision thêm `ck_sod_rules_no_generated_keys` trên
   `platform.sod_rules`: không phần tử nào của `left_scopes` hay `right_scopes` bắt đầu bằng `obj.` hay `fld.` (hai tiền
   tố của khóa sinh, ADR-0104 (Accepted) mục 4; jsonpath `@?` với `starts with`, không truy vấn con), để mục 9 của
   ADR-0104 (Accepted) ("AFTER triggers on `role_assignments` and the role privilege tables") đúng cho mọi khóa một luật nêu
   được. Revision kiểm trước khi thêm: có dòng vi phạm thì dừng với thông báo nêu khóa của luật, không xóa gì. Downgrade
   DROP ràng buộc. Ràng buộc không kiểm khóa có trong `platform.permissions` (Comments).
3. **Test của ticket 08 gieo vi phạm có sẵn theo cách khác.** Nếu một test của ticket 08 (K3 của nó, tập vi sai) gieo
   "vai trò có người vi phạm sẵn" bằng một lần khôi phục, sau ticket này lần đó bị từ chối: đổi cách gieo thành thêm một
   luật dưới `dw_migrator` sau khi các lần gán đã có (`platform.sod_rules` không có trigger, đường thứ hai mà bước 3 của
   ticket 08 nêu), giữ đúng tình trạng test đó cần. Nếu một luật test của 08 nêu khóa `obj.`/`fld.` (bước 2 nay cấm), đổi
   khóa của luật đó sang khóa danh mục riêng của ca; khóa `obj.*`/`fld.*` thêm vào vai trò thì không đổi. Nếu không test
   nào của 08 gieo bằng lần khôi phục hay nêu khóa sinh trong luật, bước này không áp và Comments ghi vậy kèm tên các tệp
   đã đọc. Mốc `down_revision` của test vi sai giữ nguyên, khác có chủ ý với MEDIUM
   (h) của ticket 08: (h) giữ lớp chống hồi quy cho lần viết lại không đổi câu trả lời, còn ticket này đổi có chủ ý đúng
   một câu trả lời (lần khôi phục), tập lần ghi của test vi sai không có lần khôi phục nào, nên mọi dòng vẫn bằng nhau ở
   hai database và test vẫn so trước và sau ticket 08.
4. **Test** (integration, tệp mới `packages/python/dw_platform/tests/integration/test_role_restore_separation_of_duties.py`,
   không sửa `test_tenant_roles.py` trừ đúng bước 3): mỗi ca trên một tenant gieo mới dưới `dw_migrator`; dựng vi phạm
   theo thứ tự gán vai trò R (vế phải) cho P, xóa mềm R, gán vai trò L (vế trái) cho P (được nhận: R không tính), rồi
   khôi phục R. Mỗi luật test gieo (bảng toàn cục, không `tenant_id`) mang khóa riêng của ca (`sod_<hex>`) trên khóa danh
   mục riêng của ca, và được xóa (miễn trừ trước, rồi luật) ở phần dọn dẹp chạy cả khi test lỗi, như
   `packages/python/dw_platform/tests/integration/test_sod_waivers.py:110-138`. Các ca ở bảng Kiểm soát.
5. `reviewing-feature-security` (ranh giới 1, 2, 6 cho trigger mới), `mutations/09.yaml` một đột biến mỗi dòng ở cột
   "Đột biến" dưới đây, không chạy `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng tay. Không bảng,
   quyền vai, hàm mới hay bước offboarding mới, nên `test_rls_coverage.py`, `test_privileges.py` và
   `test_offboarding_coverage.py` không đổi và phải xanh.

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                  | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Đột biến (`mutations/09.yaml`)                                                                                                                                                                                                                                                 |
| --- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| K1  | Khôi phục vai trò không để ai vi phạm luật | P giữ L, R xóa mềm có lần gán của P, khôi phục R dưới `dw_migrator` → 23514 `ck_roles_sod_memberships`, `HINT` là luật, `DETAIL` có P, R vẫn xóa mềm. Luật miễn trừ được: miễn trừ đề xuất chưa xác nhận → từ chối; đã xác nhận rồi thu hồi → từ chối; đã xác nhận còn hiệu lực → nhận. Không ai vi phạm → nhận; P giữ R chỉ qua lần gán đã hết hạn → nhận. P đã vi phạm sẵn (luật thêm sau các lần gán): khôi phục vai trò V chỉ mang khóa ngoài luật mà P có gán → từ chối; xóa mềm vai trò X của P → nhận | (a) bỏ trigger mới; (b) bỏ mệnh đề `WHEN` (trigger bắn cả khi xóa mềm: ca xóa mềm đỏ); (c) đảo chiều `WHEN`; (d) nhánh `tenant_roles` lấy tập người rỗng; (e) chép phép trả sớm của ticket 08 vào nhánh mới (không xét khi vai trò không mang khóa thuộc luật): ca V được nhận |
| K2  | Chỉ người giữ ở chính tenant đó được xét   | P là thành viên tenant A và B. Ở B, P vi phạm sẵn (luật thêm sau các lần gán ở B); ở A, P chỉ giữ R: khôi phục R ở A → nhận. Một người khác Q ở A, dựng như ca vi phạm của K1 (Q giữ L, vai trò R2 xóa mềm có gán của Q), khôi phục R2 → vẫn từ chối                                                                                                                                                                                                                                                         | nhánh `tenant_roles` xét `sod_violation` ở mọi tenant mà người giữ là thành viên (tenant của từng membership của họ) thay vì chỉ `NEW.tenant_id`: lần khôi phục ở A bị từ chối vì vi phạm ở B                                                                                  |
| K3  | Luật tách nhiệm không nêu khóa sinh        | INSERT `platform.sod_rules` dưới `dw_migrator` với `left_scopes` `["obj.lead.read"]` → 23514 `ck_sod_rules_no_generated_keys`; `right_scopes` `["fld.lead.phone.edit"]` → cùng ràng buộc; khóa danh mục ở cả hai vế → nhận                                                                                                                                                                                                                                                                                   | (a) bỏ ràng buộc; (b) ràng buộc chỉ xét `left_scopes`                                                                                                                                                                                                                          |

## Tiêu chí chấp nhận

- [ ] RB14: K1, ca khôi phục vi phạm bị từ chối với 23514 `ck_roles_sod_memberships`, `HINT` là khóa luật, `DETAIL` có
      id của P, và sau lần từ chối `deleted_at` của R khác NULL; hai ca miễn trừ chưa xác nhận và đã thu hồi bị từ chối;
      ca khôi phục vai trò V chỉ mang khóa ngoài luật khi P đã vi phạm sẵn bị từ chối; ca miễn trừ còn hiệu lực, ca không
      vi phạm, ca lần gán đã hết hạn và ca xóa mềm khi có người vi phạm sẵn được nhận; sai nếu một lần khôi phục vi phạm
      được nhận, một ca được nhận bị từ chối, hay một trong năm đột biến của K1 vẫn xanh. Ở commit gốc ca vi phạm được nhận.
- [ ] R5.1: K2, ca hai tenant nhận lần khôi phục ở A dù P vi phạm sẵn ở B, và vẫn từ chối ca của Q ở A; sai nếu vi phạm ở B
      làm lần khôi phục ở A bị từ chối, hay đột biến của K2 vẫn xanh.
- [ ] R5.1: K3, hai lần INSERT luật nêu `obj.`/`fld.` bị từ chối với `ck_sod_rules_no_generated_keys`, luật nêu khóa danh
      mục được nhận; sai nếu một trong hai được nhận, hay một trong hai đột biến của K3 vẫn xanh.
- [ ] R5.1: các tệp test integration ticket 08 thêm (tên theo Comments của ticket 08) xanh sau bước 3, và không test nào
      trong repo còn gieo vi phạm sẵn bằng lần khôi phục; sai nếu một test của ticket 08 đỏ hay bị bỏ qua.

- [ ] Xong: `uv run python -m pytest packages/python/dw_platform/tests/integration/test_role_restore_separation_of_duties.py packages/python/dw_platform/tests/integration/test_tenant_roles.py packages/python/dw_platform/tests/integration/test_separation_of_duties.py packages/python/dw_platform/tests/integration/test_service_principals_db.py packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py` xanh.

## Nguồn

- `db/migrations/versions/b5677d345bc1_tenant_roles.py:1161-1166` (hai trigger tách nhiệm), `db/migrations/versions/b5677d345bc1_tenant_roles.py:584-628` (`enforce_role_separation_of_duties`), `db/migrations/versions/b5677d345bc1_tenant_roles.py:522-528` (`sod_held_keys`); spec: R5.1, RB14.
- `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:301-318` (`assigned_grants` lọc vai trò đã xóa), `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:73-100` (`_earlier`, `_patched`).
- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:548-550`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:654-702`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:94-95`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:513-515`.
- `db/migrations/versions/557e6907195e_service_principals_run_as.py:348-351`, `db/migrations/versions/557e6907195e_service_principals_run_as.py:444-446`; `packages/python/dw_platform/tests/integration/test_service_principals_db.py:348-371`.
- `db/migrations/versions/b9862fa13a80_platform_separation_of_duty_rules_guard_.py:53-79` (`platform.sod_rules`).
- Spec, "Quyết định" 24/10/2026 (D11: đặt lại `deleted_at` về NULL không phải thay đổi chỉ siết); ADR-0104 (Accepted) mục 9; Comments của ticket 08 (MEDIUM (c), cùng ngày).

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cắt từ MEDIUM (c) của gate ticket 08 (HIGH ngoài ticket đó). Đọc lại ở
  head: kẽ hở có thật như mô tả ở tầng database, nhưng hẹp hơn: dưới mọi vai trò trừ `dw_migrator`, lần khôi phục đã bị
  `rbac_two_people` từ chối vì không loại đề xuất nào khớp op `role_restore`; nên ticket này là tầng cuối cho lần khôi
  phục, không mở hay đóng một route. `Blocked by: 08`: cả hai thay thân `platform.enforce_role_separation_of_duties`,
  ticket này dựng từ thân của 08 và sửa cách gieo trong test của 08, nên không dựng cạnh nhau. Bước 2 (ràng buộc trên
  `sod_rules`) thay cho trigger tách nhiệm trên hai bảng quyền của ticket 04: không luật nào nêu khóa sinh ở head, và
  một luật như thế là lựa chọn của migration, nên chặn nó rẻ hơn và ồn hơn một trigger nữa. Nếu sai thì: (1) một luật
  cần khóa `obj.*`/`fld.*` thì ticket của luật đó bỏ ràng buộc và thêm trigger tách nhiệm trên
  `platform.tenant_role_object_privileges` và `studio.field_permissions` (đọc khóa qua `platform.record_privilege_keys`);
  (2) một route khôi phục sau này (loại đề xuất mới) dùng trigger này như mọi người ghi, và mang theo cửa sổ đồng thời
  ở dòng gate dưới.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, ranh giới
  1, 2, 3, 5, 6, vì ticket có migration). Hai HIGH, sửa ở ticket. (1) Test âm K2 không đỏ được: `tenant_roles.id` là khóa
  chính toàn cục, nên đột biến "bỏ lọc `NEW.tenant_id` khi lấy người giữ" tương đương code gốc; K2 nay đặt P vi phạm sẵn ở
  B và khôi phục ở A phải được nhận, đột biến là xét mọi tenant của người giữ. (2) Đột biến "bỏ `WHEN`" sống vì không ca
  nào xóa mềm khi có người vi phạm sẵn; K1 thêm ca đó (nhận), và các đột biến tách thành một cột riêng. MEDIUM, sửa: luật
  test là bảng toàn cục, mỗi ca một khóa và dọn cả khi lỗi (`test_sod_waivers.py:110-138`); mốc `down_revision` của test
  vi sai giữ nguyên, nêu rõ vì sao khác MEDIUM (h) của 08; bước 3 nói làm gì khi 08 không gieo bằng lần khôi phục; ca
  miễn trừ đã thu hồi; ràng buộc đổi tên `ck_sod_rules_no_generated_keys` vì nó chỉ cấm hai tiền tố, không kiểm danh mục.
  Nếu sai thì: lỗi lộ ra khi dựng, ghi ở đây.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới, cùng hai brief). Một HIGH, nhận rủi ro,
  không chặn: lần khôi phục và một lần xác nhận gán vế kia cho cùng người, ở hai giao dịch đồng thời, có thể cùng qua, vì
  mỗi bên xét tách nhiệm trước khi khóa dòng version (đọc từ thứ tự trigger, chưa đo). Cửa sổ đó có sẵn cho hai lần gán
  đồng thời hôm nay (R5.1 nói chung, không riêng lần khôi phục), và ở head chỉ `dw_migrator` khôi phục được, nên ticket
  này không mở thêm gì. Chủ: một ticket mới của spec này, phiên điều phối cắt (đo cuộc đua như Câu 3 của discovery/08,
  rồi khóa trước `sod_violation` nếu số đo cho thấy lọt), cùng đường `dw_migrator` đổi `memberships.user_id` hay
  `workspace_id` (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1000-1015`), cũng mang lần
  gán sang người khác mà không trigger tách nhiệm nào xét. Nếu sai thì: cắt ticket đó trước và cho ticket này chờ nó.
  Sửa ở ticket: K1 thêm ca khôi phục vai trò chỉ mang khóa ngoài luật khi người giữ đã vi phạm sẵn (từ chối) với đột
  biến (e) chép phép trả sớm của 08; K2 dùng người Q cho ca từ chối, hết mâu thuẫn với "ở A, P chỉ giữ R"; bước 3 xử lý
  luật test của 08 nêu khóa sinh. MEDIUM, không sửa, người dựng đọc trước: (a) thêm một luật khi đã có người giữ cả hai vế
  vẫn im lặng: nhận, luật chỉ migration ghi và test của 08 dựa vào đường đó; Nếu sai thì: migration thêm luật kiểm trước
  và dừng; (b) ràng buộc không kiểm khóa có trong `platform.permissions`, nên luật gõ sai không khớp ai: nhận; Nếu sai
  thì: trigger kiểm danh mục; (c) ADR-0104 (Accepted) mục 9 nói trigger trên "the role privilege tables": bước 2 làm câu
  đó đúng bằng cách cấm khóa sinh trong luật, ghi ở "Quyết định" của spec, khuyến nghị một dòng Amendments cho mục 9 khi
  phiên điều phối sửa ADR; (d) lần khôi phục dưới `dw_migrator` không ghi audit, như mọi lần ghi của migration; (e) bước
  kiểm trước của ràng buộc không có test. Sửa sau lượt xác nhận không được người đọc mới đọc lại; người dựng đọc bước 1-3
  và K1 trước.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
