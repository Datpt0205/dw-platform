# 16 — Membership không vai trò qua `PUT .../memberships`, và không đề xuất nào chỉ người nhận xác nhận được

Status: ready-for-agent
Blocked by: 03, 04, 08, 11
Area: studio
Yêu cầu: R3.3, R6.4, R7.1, R7.3, R7.6, R8.2, RB8, RB17, RB21, RB22, RB24, RB32

## Mục tiêu

Một công ty có đúng hai chủ sở hữu không cho chủ nào một membership ở workspace mới qua API, nên chủ không làm việc được
dưới `X-Workspace-Id` của workspace đó (AccessContext đọc membership của workspace đang làm việc). Build lane của
marketing-pilot/02 đo trên API thật (6/11/2026) hai lỗ:

- `PUT /api/v1/admin/members/{user_id}/memberships` với `role_keys: []` cho một workspace chưa có membership trả 200 và
  lặng lẽ bỏ workspace đó (failure-modes #1, #7): service coi "không vai" là "không membership". Cùng luật làm web xóa
  membership không vai của người ở workspace khác mỗi lần lưu vai trò, vì `membershipsBody`
  (`apps/web/components/admin/role-assignment.ts`) gửi lại nguyên các membership khác, kể cả membership `role_keys: []`.
- Gán vai trò cho chủ kia thì chủ kia là người nhận, không xác nhận được (R6.4, RB17), mà `has_checker` chỉ trừ người đề
  xuất, nên với hai người giữ `platform.roles.bind` lần đề xuất được ghi (202) rồi không ai xác nhận được tới khi hết hạn:
  trái R7.3 ("không có người thứ hai `active` nào giữ quyền cần để xác nhận" thì 409 và không ghi đề xuất).

Membership không vai trò không cho khóa nào (ticket 03 bước 6, lý do ghi ngay membership của lời mời): quyền mức
`workspace` neo ở workspace của lần gán, không ở membership (ADR-0104 (Accepted) mục 3), và khóa mức `tenant` đã với tới
mọi workspace (R2.3); tầm với bản ghi (`studio.v_principal_grants` nối lần gán) và người giữ khóa (`platform.scopes_in`)
không đổi. Hệ quả có chủ ý, như membership của lời mời hôm nay: người đó có AccessContext dưới `X-Workspace-Id` của
workspace đó với đúng các khóa đã giữ, là người nhận bàn giao hợp lệ ở đó (record-access:R8.5, `work_queue.py`
`is_person_in`), và workspace vào `studio.v_principal_workspaces` (`workspace_ids`, hôm nay không câu nào đọc). Nên lát này cho `role_keys: []` nghĩa đúng chữ: workspace có trong thân là một membership người đó
có sau lệnh, không vai trò nào; tạo nó là việc của `platform.members.write` (khóa loại `tenant`), một người cộng audit,
không đề xuất (R7.1 chỉ kể thay đổi vai trò). Và lần đề xuất gán vai trò mà ngoài người đề xuất chỉ còn người nhận giữ
`platform.roles.bind` trả 409 `no_checker_available` (R7.3). Lối "đề xuất vai trò rồi rút" để lại membership không vai là
có chủ ý, như lời mời (ghi ở bước 3).

## Việc cần làm

Đọc ở `bb622179` (6/11/2026):

- `RoleAssignmentService.set_memberships` (`packages/python/dw_platform/src/dw_platform/application/role_assignments.py:227-279`):
  vòng qua `held.memberships ∪ desired`; `want = desired.get(ws, frozenset())`, nên workspace vắng và workspace
  `role_keys: []` như nhau: `dropping = now is not None and not want`, `new` chỉ khi `now is None and want`. `_check`
  (`role_assignments.py:419-462`) trả sớm khi `not plan.touches_roles` (dòng 428), sau đó mới kiểm DW principal, tài khoản
  dịch vụ, `platform.rbac_refusals` và `has_checker(context, ROLES_BIND)` (dòng 461).
- `SqlRoleAssignmentRepository.has_checker` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/role_assignments_repo.py:116-122`)
  chạy `HAS_CHECKER` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/role_admin_repo.py:92-95`):
  `EXISTS` trên `platform.checker_candidates(t, k, proposer)`, hàm trừ người đề xuất, chỉ người `human` `active`
  (`db/migrations/versions/b5677d345bc1_tenant_roles.py:476-494`). Không người nhận nào bị trừ.
- `_write` (`role_assignments_repo.py`, sau dòng 270) ghi membership mới với `ON CONFLICT DO NOTHING` và một audit
  `platform.membership.grant` mỗi membership tạo ra, `_require_workspaces` (404 cho workspace ngoài tenant) trước đó; một
  kế hoạch chỉ có `new_memberships` đã đi được đường này (lời mời).
- Route `set_memberships` (`apps/api/src/dw_api/routes/v1/admin_members.py:297-331`), docstring nói "one left out, or
  with no role, goes with every role on it"; fake của unit test
  (`apps/api/tests/unit/fake_role_assignments.py:195`, `has_checker`) theo cùng Protocol.
- Test hiện có dùng `role_keys: []` trên membership đang có: `apps/api/tests/integration/test_role_admin_api.py:1123`
  (gỡ vai trò của người được mời, khẳng định 200 và có audit `platform.role_assignment.revoke`): sau lát này membership ở
  lại, vai trò vẫn bị gỡ, test giữ xanh không sửa.

Việc:

1. **Luật của thân** (`set_memberships`, docstring của service, của route và module): mỗi workspace trong thân là một
   membership người đó có sau lệnh; `role_keys` là toàn bộ vai trò loại `role` trên nó, `[]` là không vai trò nào; workspace
   vắng khỏi thân mất membership cùng mọi vai trò trên nó (như nay). Cụ thể, `present = ws in desired`:
    - `now is None and present` → `new.append(ws)` (kể cả `role_keys: []`);
    - `now is not None and not present` → `dropped.append(ws)`, và chỉ khi đó bộ quyền bổ sung trên nó đi cùng (D6 của
      ticket 03);
    - `now is not None and present and want == ∅` → membership ở lại, mỗi vai trò loại `role` trên nó là một lần gỡ (R7.6:
      áp ngay, một audit mỗi lần gỡ, cần `platform.roles.bind` qua `_check` như mọi lần gỡ, R8.2).
2. **Hai lần từ chối trước lần ghi đầu**, trong `_check` trước câu trả sớm `not plan.touches_roles` (ADR-0104 (Accepted)
   mục 10: một lần từ chối, cả request không ghi gì):
    - kế hoạch có `new_memberships` cho chính người gọi (`plan.user_id == context.principal_id`) → 403
      `rbac_self_assignment` (cùng `PermissionDeniedError` mà `rbac_refusal_error` dựng cho mã đó), không ghi gì: hôm nay
      không ai tự đặt mình vào workspace mới được (lần thêm vai trò cho mình bị R6.4 từ chối), lát này không mở lối đó
      (quyết định ở Comments). Chỉ `new_memberships`: lần tự gỡ vai trò hay tự bỏ một workspace của chính mình vẫn đi luật
      gỡ hiện có (R7.6, `platform.rbac_refusals`), không đổi;
    - kế hoạch có `new_memberships` cho principal của một DW (`held.dw_principal`) → 409 `dw_principal_roles_fixed` như
      lần gán vai trò cho nó hôm nay (digital-worker:R1.17), không ghi gì. Tài khoản dịch vụ khác (`kind = 'service'`,
      không phải principal của DW) nhận membership không vai như người (digital-worker, Quyết định 29/10/2026 lượt xác
      nhận: R1.17 không chạm service principal khác; quyết định ở Comments).
3. **Lối rút đề xuất** không đổi: membership mà lời mời, `POST /api/v1/admin/members` hay `PUT .../memberships` ghi cùng
   một đề xuất `assignment_grant` ở lại khi đề xuất bị rút hay hết hạn, không cho quyền nào; gỡ nó bằng
   `DELETE /api/v1/admin/members/{user_id}?workspace_id=` hay `PUT .../memberships` không có workspace đó. Ghi một câu ở
   docstring của service; không đổi code, không tiêu chí (đã đúng ở commit gốc).
4. **Người xác nhận khác người nhận** (R7.3): `RoleAssignmentRepositoryPort.has_checker` nhận thêm
   `assignee: uuid.UUID | None`; câu SQL thành
   `SELECT EXISTS (SELECT 1 FROM platform.checker_candidates(CAST(:t AS uuid), CAST(:k AS text), CAST(:a AS uuid)) AS c(id) WHERE c.id IS DISTINCT FROM CAST(:x AS uuid))`,
   một hằng riêng ở `role_assignments_repo.py` (không sửa `HAS_CHECKER` của `role_admin_repo.py`, mà các đề xuất vai trò
   dùng: ở đó không có người nhận). `_check` truyền `plan.user_id` khi `plan.grants`. Không hàm SQL mới, không migration:
   `checker_candidates` vẫn là chủ của "ai xác nhận được", câu lọc chỉ trừ người mà R6.4 (`platform.rbac_refusals`) đã cấm
   xác nhận; hai nơi lệch nhau thì lệch ồn ào (409 thừa hay 403 lúc xác nhận), có test cho cả hai (K4). Fake của unit test
   theo chữ ký mới và trừ người nhận như bản SQL (`.claude/rules/code-quality.md`, Liskov): nó trả sai khi ngoài người đề
   xuất chỉ người nhận là ứng viên; cách fake giữ tập ứng viên là việc của người dựng, các test đặt `repo.checker = False`
   giữ nghĩa cũ.
5. `make generate-contracts` (docstring của route đổi mô tả trong OpenAPI); web không đổi.
6. Test (integration, tệp mới `apps/api/tests/integration/test_member_placement_api.py`, dùng fixture `api` và các helper
   của `test_role_admin_api.py` như `test_record_privileges_api.py` đã làm: `_tenant`, `_who`, `_set_memberships`,
   `_reason`, `_proposals`, `_audits`, `_rows`; người giữ khóa gieo bằng `admin(...)` hay `plant_role` dưới `dw_migrator`):
   xem bảng và tiêu chí. Ở `test_role_admin_api.py` chỉ sửa test mà tenant gieo chỉ có người đề xuất và người nhận giữ
   `platform.roles.bind`, nên bước 4 đổi lần đề xuất của nó từ 202 sang 409: thêm một người giữ khóa thứ ba
   (`await _who(api, t, admin())`), không đổi khẳng định nào. Đã biết một: `test_nobody_assigns_a_role_to_themselves`
   (`test_role_admin_api.py:799-820`, lần đề xuất cho `second` ở dòng 814; lần xác nhận của `second` vẫn 403, lớp
   `platform.rbac_refusals` của K4). Test khác đỏ vì cùng lẽ thì sửa cùng cách và kể tên ở Comments lúc dựng. Ca hai chủ gieo một tenant mà ngoài hai chủ không ai giữ
   `platform.roles.bind` (`_tenant` không gieo thêm người giữ khóa; khẳng định điều đó đầu test bằng
   `platform.checker_candidates`).
7. `reviewing-feature-security` (ranh giới 1, 2 và 6; 3, 4, 5 không áp), `mutations/16.yaml` một đột biến mỗi dòng ở cột
   "Đột biến", không chạy `scripts/mutate.py` (lúc đóng hàng đợi). Độ trễ: lần đề xuất gán vai trò đọc `checker_candidates`
   như hôm nay với một vế lọc; đo P50/P95/P99 của `PUT .../memberships` (một membership không vai, và một vai trò thêm) lúc
   đóng hàng đợi (`.claude/rules/latency.md`).

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                                                        | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Đột biến (`mutations/16.yaml`)                                                                                                                            |
| --- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | Membership không vai trò chỉ người giữ `platform.members.write` tạo (R8.2)       | Người giữ `platform.roles.bind` mà không giữ `platform.members.write` gửi `PUT` thêm workspace W với `role_keys: []`, không `Idempotency-Key` (dependency idempotency cũng hỏi `platform.members.write`, sẽ che đột biến) → 403, 0 membership mới, 0 audit                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | (a) bỏ `authz.require(... MEMBERS_WRITE ...)` đầu `set_memberships` (đỏ: 200 và membership có)                                                            |
| K2  | Không đặt người của công ty khác, hay vào workspace của công ty khác (R3.3)      | Người gọi của A: `PUT` cho một người chỉ có membership ở B → 404, 0 membership; `PUT` cho người của A với `workspace_id` của B và `role_keys: []` → 404, 0 membership ở B hay A, 0 audit                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | (a) bỏ lời gọi `_require_workspaces` trong `_write` (đỏ: vế thứ hai không còn 404)                                                                        |
| K3  | Không tự đặt mình vào workspace mới (R6.4)                                       | Chủ O1 gửi `PUT` cho chính mình, thân giữ nguyên membership `main` (`tenant_owner`) và thêm W với `role_keys: []` → 403 `rbac_self_assignment`, 0 membership mới, 0 audit; đối chứng: O1 gửi cho O2 cùng thân → 200                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | (a) bỏ phép kiểm người gọi là người nhận của bước 2 (đỏ: 200)                                                                                             |
| K4  | Không đề xuất nào chỉ người nhận xác nhận được (R7.3)                            | Tenant có đúng hai người giữ `platform.roles.bind`, O1 và O2 (hai chủ): O1 gửi `PUT` cho O2 thêm W với một vai trò không trọng yếu → 409 `no_checker_available`, 0 dòng đề xuất, 0 membership mới (cả request bị từ chối); đối chứng: thêm C giữ `platform.roles.bind` → 202, một đề xuất, C xác nhận → 200; cùng tenant hai người, O1 gửi `PUT /api/v1/admin/members/{O2}/permission-sets` thêm một bộ quyền → 409 `no_checker_available` (bước 4 áp cho mọi đường qua `_check`: `PUT .../memberships`, `PUT .../permission-sets`, `POST /api/v1/admin/members`; lời mời không đổi vì người được mời chưa `active`); O2 xác nhận một đề xuất cho chính mình (gieo dưới `dw_migrator` khi có C) → 403 `rbac_self_assignment` (lớp kia của cùng luật, failure-modes #3 lần năm) | (a) `_check` gọi `has_checker` không truyền người nhận (đỏ: 202 và một đề xuất không ai xác nhận được); (b) câu SQL bỏ vế `IS DISTINCT FROM` (đỏ như (a)) |
| K5  | DW principal không nhận membership mới (digital-worker:R1.17)                    | `PUT` cho principal của một DW thêm W với `role_keys: []` → 409 `dw_principal_roles_fixed`, 0 membership mới                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | (a) bỏ phép kiểm `held.dw_principal` cho `new_memberships` của bước 2 (đỏ: 200)                                                                           |
| K6  | `[]` trên membership đang có giữ membership, gỡ vai trò qua luật gỡ (R7.6, R8.2) | Người P có membership ở `main` với `member`, ở W với vai trò không trọng yếu R và một membership không vai ở Y; thân gửi `main: ["member"]` nguyên. (i) Người giữ `members.write` mà không giữ `roles.bind` gửi `{main: [...], W: [], Y: []}` → 403, R còn; (ii) người giữ cả hai gửi cùng thân → 200, R gỡ với đúng một audit `platform.role_assignment.revoke`, không đề xuất, membership W và Y còn; (iii) lần lưu vai trò ở workspace X như web gửi (`Y: []` gửi lại nguyên) → Y còn                                                                                                                                                                                                                                                                                       | (a) nhánh `now is not None and present and want == ∅` bỏ membership như hôm nay (đỏ: (ii), (iii) mất W, Y)                                                |

## Tiêu chí chấp nhận

- [ ] R7.1 (RB21): người giữ `platform.members.write` mà không giữ `platform.roles.bind` gửi `PUT` thêm W với
      `role_keys: []` cho người P của công ty (thân giữ nguyên các membership đang có) → 200, thân trả W với
      `role_keys: []`, `proposals` rỗng; một dòng `platform.memberships` mới, đúng một audit `platform.membership.grant`, 0
      dòng `platform.role_change_requests`, 0 dòng `platform.role_assignments` mới, `platform.effective_grants` của P không
      đổi. Đối chứng hai người: người giữ cả hai khóa, ở tenant có người thứ ba giữ `platform.roles.bind` khác người gọi và
      P, gửi thân thêm W2 với một vai trò không trọng yếu → 202, vai trò là đề xuất, chưa có hiệu lực tới khi người thứ ba
      xác nhận. Sai nếu W vắng sau lệnh (hành vi ở commit gốc), hay có đề xuất hay gán nào ở lệnh không vai. Ca của
      marketing-pilot/02: tenant hai chủ, O1 đặt O2 vào W và O2 đặt O1 vào W bằng `role_keys: []` (thân giữ `main`
      `tenant_owner`) → hai lần 200, rồi `GET /api/v1/me` của mỗi chủ dưới `X-Workspace-Id` W → 200.
- [ ] R7.1 (RB21): K5, principal của DW nhận `PUT` thêm membership → 409 `dw_principal_roles_fixed`, 0 membership; sai nếu
      đột biến (a) của K5 vẫn xanh.
- [ ] R8.2 (RB24): K1, người không giữ `platform.members.write` → 403, 0 membership; sai nếu đột biến (a) của K1 vẫn xanh.
      Test gửi không `Idempotency-Key`. Ca hồi quy: đã 403 ở commit gốc; sau lát này nó là cửa duy nhất của membership không vai (không vai trò nào chạm
      tới, nên `platform.roles.bind` và `platform.rbac_refusals` không được hỏi).
- [ ] R3.3 (RB8): K2, người của B hay workspace của B qua `PUT` của A → 404, 0 dòng đổi ở cả hai công ty; sai nếu đột biến
      (a) của K2 vẫn xanh.
- [ ] R6.4 (RB17): K3, tự đặt mình vào workspace mới → 403 `rbac_self_assignment`, 0 dòng; đặt chủ kia → 200; sai nếu đột
      biến (a) của K3 vẫn xanh. Ở commit gốc lần tự đặt trả 200 và không ghi gì (W bị bỏ lặng lẽ), nên đỏ.
- [ ] R7.3 (RB22): K4, đề xuất mà chỉ người nhận xác nhận được → 409 `no_checker_available`, 0 đề xuất, 0 membership, qua
      `PUT .../memberships` và qua `PUT .../permission-sets`; có người thứ ba → 202 và xác nhận được; sai nếu đột biến (a) hay (b) của K4 vẫn xanh. Ở commit gốc lần đề xuất trả 202.
- [ ] R7.6 (RB32): K6, `role_keys: []` trên membership đang có vai trò → 200, vai trò gỡ với một audit, membership ở lại;
      thiếu `platform.roles.bind` → 403; membership không vai ở workspace khác gửi lại nguyên `[]` thì ở lại; sai nếu đột
      biến (a) của K6 vẫn xanh.
- [ ] Xong: `uv run python -m pytest apps/api/tests/integration/test_member_placement_api.py apps/api/tests/integration/test_role_admin_api.py apps/api/tests/integration/test_idempotent_operations.py apps/api/tests/unit/test_admin_members_endpoint.py apps/api/tests/unit/test_tenant_members_endpoint.py apps/api/tests/unit/test_idempotency_dependency.py apps/api/tests/contract/test_openapi_snapshot.py packages/python/dw_platform/tests/integration/test_tenant_members.py` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/role_assignments.py:227-279`, `packages/python/dw_platform/src/dw_platform/application/role_assignments.py:419-462`; spec: R7.1, R7.3, R7.6, R8.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/role_assignments_repo.py:116-122`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/role_admin_repo.py:92-95`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:476-494`; spec: R7.3, RB22.
- `apps/api/src/dw_api/routes/v1/admin_members.py:297-331`; `apps/api/tests/unit/fake_role_assignments.py:195`; `apps/web/components/admin/role-assignment.ts` (`membershipsBody`).
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py` (`_access_in`: AccessContext cần membership của workspace đang làm việc); `db/migrations/versions/ebb17244abc6_permission_catalogue.py:221` (`platform.members.write` loại `tenant`).
- `apps/api/tests/integration/test_role_admin_api.py:516`, `apps/api/tests/integration/test_role_admin_api.py:1123`.
- Spec: R2.3, R3.3, R6.4, R7.1, R7.3, R7.6, R8.2, RB8, RB17, RB21, RB22, RB24, RB32; ticket 03 bước 6 và Comments (D6); ADR-0104 (Accepted) mục 3, mục 6, mục 10; marketing-pilot: R1.1.

## Comments

- 2026-11-06 (agent, theo ủy quyền 31/10/2026): cắt từ phát hiện 2 của build lane marketing-pilot/02 (6/11/2026, đo trên
  API thật). Quyết định:
    - (Q1) `role_keys: []` tạo membership không vai trò, một người, không đề xuất, thay vì 422: membership không cho quyền
      nào (quyền `workspace` neo ở workspace của lần gán, `tenant` đã với mọi workspace, ADR-0104 (Accepted) mục 3; R2.3),
      ticket 03 đã ghi membership của lời mời ngay vì lẽ đó, và 422 để công ty hai chủ không có lối nào cho chủ một
      membership ngoài đề xuất rồi rút. Nếu sai thì: `role_keys: []` cho workspace chưa có membership trả 422
      `validation_failed` với con trỏ `/memberships/<n>/role_keys`, membership không vai chỉ qua một route riêng có hai người.
    - (Q2) `[]` trên membership đang có giữ membership và gỡ vai trò, workspace vắng mới bỏ membership: một nghĩa cho thân
      (trạng thái muốn có), và web hết xóa lặng lẽ membership không vai của người ở workspace khác. Nếu sai thì: `[]` trên
      membership đang có giữ nghĩa cũ (bỏ membership), chỉ workspace chưa có membership mới được tạo không vai; web gửi
      lại membership không vai thì mất, ghi thành ticket web riêng.
    - (Q3) Không tự đặt mình vào workspace mới (403 `rbac_self_assignment`), vì hôm nay không ai làm được điều đó (lần thêm
      vai trò cho mình bị R6.4 chặn) và lần gieo của marketing-pilot/02 không cần (hai chủ đặt nhau); mặc định đóng
      (failure-modes #7). Nếu sai thì: bỏ phép kiểm đó, K3 thành đối chứng 200.
    - (Q4) Lối đề xuất rồi rút để lại membership không vai là có chủ ý, như lời mời; chỉ ghi ở docstring. Nếu sai thì: lần
      rút hay hết hạn của đề xuất `assignment_grant` cuối của một membership không vai gỡ cả membership, một ticket riêng
      có migration (lane 1).
    - (Q5) R7.3 trừ người nhận ở câu hỏi của service, không ở `platform.checker_candidates`: không migration, các đề xuất
      vai trò (không có người nhận) không đổi. Nếu sai thì: `checker_candidates` nhận thêm tham số người nhận, một revision
      (lane 1), `HAS_CHECKER` dùng chung.
      Không migration, không bảng, cột, quyền vai hay route mới: `test_rls_coverage.py`, `test_privileges.py`,
      `test_offboarding_coverage.py` không đổi. Không chạy song song với custom-objects/12: cả hai đổi ảnh chụp OpenAPI và
      kiểu TS (`.claude/rules/wave-close.md`, hai lane). Cặp không đường phụ thuộc trong spec này: 06 (`ready-for-agent`,
      migration khóa hai cột cũ của `platform.memberships`) và 16 không chung bảng (16 không đổi lược đồ, chỉ ghi dòng qua
      đường có sẵn), route, migration, config hay prompt.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk một
  subagent, ranh giới 1, 2, 6; 3, 4, 5 không áp). Một HIGH, sửa ở ticket: (1) tiêu chí R7.1 cho người chỉ giữ
  `platform.members.write` gửi cả vế thêm vai trò mà đòi 202, trái R8.2 (`_check` trả 403) và K4 (cần người xác nhận thứ
  ba): tách thành lệnh không vai của người chỉ giữ `members.write` (200) và đối chứng hai người của người giữ cả hai khóa
  ở tenant có người thứ ba (202). MEDIUM, sửa: (2) Mục tiêu nêu hệ quả có chủ ý của membership không vai (AccessContext ở
  workspace đó với khóa đã giữ, người nhận bàn giao hợp lệ, `workspace_ids`), thay câu "không cho quyền nào"; (3) tài
  khoản dịch vụ khác principal của DW nhận membership không vai như người. Nếu sai thì: `kind = 'service'` nhận 409
  `dw_principal_roles_fixed` như principal của DW cho mọi membership mới. (4) K3 chỉ chặn `new_memberships`; tự gỡ vẫn
  theo luật gỡ. (5) K6 gieo P có `main`. LOW, sửa: (6) dòng `Xong` thêm `test_idempotency_dependency.py` (dùng fake) và
  `test_idempotent_operations.py` (gọi route thật); `Blocked by` thêm 04, 08, 11 (cùng thân `platform.rbac_refusals` mà
  lần gỡ của K6 đi qua; script báo chạm chung, cả ba `resolved`). MEDIUM, không sửa, người dựng đọc trước:
  (a) K3, K5 và luật workspace của công ty mình chỉ ở service: SQL thô dưới `dw_app` vào `platform.memberships` vẫn nhận
  membership cho chính `app.user_id`, cho principal của DW (ràng buộc `dw_principal_roles_fixed` chỉ còn trên
  `role_assignments`, `d2b57239ef50`) và trỏ workspace bằng khóa ngoại một cột. R6.2 bao lần gán vai trò, không
  membership; membership không cho khóa nào nên luật một lớp là có chủ ý. Nếu sai thì: một trigger trên INSERT
  `platform.memberships` (migration, lane 1). (b) `has_checker` vẫn chỉ hỏi người giữ `platform.roles.bind`, không luật
  giữ quyền của vai trò trọng yếu (ADR-0104 (Accepted) mục 6): người thứ ba chỉ giữ `bind` mà vai trò trọng yếu thì đề
  xuất vẫn được ghi rồi bị từ chối lúc xác nhận; có từ ticket 03, ngoài lát này. Câu lọc người nhận chạy trên kết quả
  của `platform.checker_candidates`, hàm vẫn là chủ duy nhất của "ai xác nhận được" (ADR-0104 (Accepted) mục 10), không cần
  Amendment. (c) Workspace đã lưu trữ: `_require_workspaces` không xét `archived_at`, nên lời mời và lệnh không vai cùng
  nhận nó; có từ trước, cho cả lời mời, ngoài lát này. (d) Thân `{"memberships": []}` bỏ mọi membership của người đó với
  một người (mỗi vai trò một lần gỡ qua luật gỡ); như hôm nay (`test_role_admin_api.py:516`), không đổi. (e) Hai lần đặt
  không vai giống hệt cùng lúc: `ON CONFLICT DO NOTHING` và audit chỉ khi `RETURNING` có dòng cho một membership, một
  audit; lần gửi lại cùng `Idempotency-Key` đi dependency idempotency có sẵn (R8.4); không tiêu chí riêng. (f) Cache
  AccessContext cũ: trigger `trg_z_bump_access_version` trên `platform.memberships` tăng phiên bản (R4.1, ADR-0104 (Accepted) mục 7);
  ca của marketing-pilot/02 không đọc `/me` trước lần đặt, người dựng thêm được một lần đọc trước để thấy điều đó.
  (g) Membership không vai của tài khoản dịch vụ không hiện ở `GET /api/v1/admin/members` (lọc `human`): gỡ qua
  `DELETE`, có từ trước.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới). Một HIGH, sửa ở ticket: (1)
  `test_nobody_assigns_a_role_to_themselves` (`test_role_admin_api.py:799-820`) gieo đúng hai người giữ
  `platform.roles.bind` rồi đề xuất cho người kia, nên sau bước 4 nó trả 409 và dòng `Xong` đỏ: bước 6 nay cho sửa các
  test như vậy bằng một người giữ khóa thứ ba, không đổi khẳng định. MEDIUM, sửa: (2) K1 gửi không `Idempotency-Key`, vì
  dependency idempotency hỏi lại `platform.members.write` và che đột biến; (3) bước 4 áp cho cả `PUT .../permission-sets`
  và `POST /api/v1/admin/members` (cùng `_check`), K4 thêm ca `permission-sets`. MEDIUM, không sửa: (4) ADR-0104 (Accepted)
  mục 10 nói một hàm SQL tìm người xác nhận; vế lọc người nhận nằm ngoài hàm, nên cần một câu Amendment ở ADR (ghi ở báo
  cáo gate cho người giữ ADR; lane gate không sửa ADR). Nếu sai thì: Q5 phương án sau (tham số người nhận trong
  `checker_candidates`, lane 1). (5) Lần đặt tài khoản dịch vụ trả 200 với `memberships: []` vì `view_now` đọc
  `list_members` (lọc `human`), dù membership đã ghi; chủ là org-and-principals, không tiêu chí ở đây. (6) Người giữ khóa
  thứ ba bị đình chỉ giữa `has_checker` và lần ghi đề xuất: đề xuất được ghi rồi hết hạn, như hôm nay. Sửa sau lượt này
  không được người đọc mới đọc lại (hai lượt mỗi phiên bản); người dựng đọc bước 4, bước 6 và K4 trước.
- 2026-11-06 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
