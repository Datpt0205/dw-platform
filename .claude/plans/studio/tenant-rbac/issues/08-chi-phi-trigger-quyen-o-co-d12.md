# 08 — Chi phí trigger quyền ở cỡ D12: kiểm chủ sở hữu mỗi giao dịch, luật giữ quyền theo neo, tách nhiệm bỏ khóa ngoài luật

Status: needs-triage
Blocked by: 02, 03, 04, 07
Area: studio
Yêu cầu: không (chi phí của ba trigger theo Phát hiện 2-4 của discovery/08; không đổi câu trả lời nào: R3.12, R5.1, R6.1, R6.3 và RB14, RB15, RB16, RB40 giữ bằng test hiện có cộng test bằng nhau ở đây)

## Mục tiêu

discovery/08 (FOG-38) đo ở một công ty 5.000 người: gán vai trò cho 1.000 người trong một giao dịch mất 30,2 giây, 59%
là `platform.check_owner_coverage` chạy ở mỗi lệnh; thêm 10 khóa vào một vai trò 1.000 người giữ mất 15,1 giây, chia đôi
giữa luật giữ quyền xét từng lần gán của vai trò (`holder_covers_grant` 0,65 ms × 1.000 mỗi dòng) và tách nhiệm xét lại
cả 1.000 người giữ cho mỗi khóa, kể cả khóa không thuộc luật nào. Trong suốt lần ghi đó, dòng version của công ty bị khóa,
nên mọi lần ghi quyền khác của công ty chờ (Phát hiện 6, giữ nguyên theo ADR-0104 (Accepted) mục 7). Ticket này làm ba
trigger đó tốn theo số neo và số luật thay vì số lần gán, mà không đổi lần ghi nào được nhận hay bị từ chối, nên lần ghi
lớn ngắn lại và công ty chờ ít hơn.

## Việc cần làm

1. **`check_owner_coverage` một lần mỗi giao dịch** (Phát hiện 2): hôm nay là trigger theo câu lệnh trên bốn bảng
   (`db/migrations/versions/b5677d345bc1_tenant_roles.py:1188-1198`), mỗi lệnh dựng `checker_candidates` của mọi thành
   viên (18 ms ở 5.000 người). Chuyển thành một lần ở commit theo tenant, như trigger ràng buộc hoãn
   `trg_z_bump_access_version_access_mode` (`db/migrations/versions/2f177d264a27_field_access_mode.py:77`), với một dấu
   theo giao dịch để nhiều dòng cùng tenant chạy một lần. Cảnh báo dưới hai người vẫn một lần mỗi lần xuống (R3.12,
   RB40) và vẫn trong cùng giao dịch.
2. **Luật giữ quyền theo neo** (Phát hiện 3): op `add`, `raise`, `remove`, `lower` của `platform.rbac_refusals`
   (`db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:399-435`) xét `holder_covers_grant`
   trên `DISTINCT a.workspace_id` của vai trò (≤ số workspace), như op `role_delete` đã làm (`:450-463`), thay vì từng lần
   gán; và một lần khi người làm giữ khóa ở mức `tenant`. Luật vẫn là `platform.holder_covers_grant`
   (`db/migrations/versions/557e6907195e_service_principals_run_as.py:464`), không chép sang chỗ khác.
3. **Tách nhiệm bỏ qua khóa ngoài luật** (Phát hiện 4): trên `platform.tenant_role_permissions`,
   `platform.enforce_role_separation_of_duties` (`db/migrations/versions/b5677d345bc1_tenant_roles.py:584-628`) xét lại
   mọi người giữ vai trò cho mỗi dòng; dòng có khóa không nằm ở `left_scopes` hay `right_scopes` của luật nào không thể
   tạo vi phạm mới, nên trả sớm. Dòng `role_assignments` giữ nguyên (một người).
4. Một revision (id hex của `alembic revision`), `CREATE OR REPLACE` ba hàm, downgrade dựng lại thân cũ; không bảng, quyền
   hay bước offboarding mới.
5. **Test bằng nhau** cho mỗi bước: cùng tập lần ghi (nới, siết, người làm giữ khóa ở `workspace` và ở `tenant`, khóa
   thuộc luật và ngoài luật, công ty xuống dưới hai người giữ) được nhận hay bị từ chối với cùng tên ràng buộc trước và
   sau; rồi đo lại `q2` của `make bench-rbac`.

Kiểm soát của ticket này (mã K chỉ dùng trong ticket; mỗi dòng một đột biến khi dựng):

| #   | Kiểm soát                                                | Test âm                                                                                                                                                                                                      |
| --- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| K1  | Cảnh báo dưới hai người vẫn đúng một lần, cùng giao dịch | Gỡ gán của người giữ thứ hai `platform.roles.write` → đúng một sự kiện `platform.tenant.owner_coverage_low`; sai nếu dấu theo giao dịch bỏ qua tenant thứ hai cùng giao dịch hay lần gỡ sau commit → test đỏ |
| K2  | Luật giữ quyền theo neo từ chối đúng lần ghi cũ          | Người làm giữ khóa ở `workspace` A, vai trò gán ở A và B, thêm khóa → `rbac_refusals_tenant_role_permissions`; sai nếu chỉ xét một neo → test đỏ                                                             |
| K3  | Khóa thuộc luật vẫn qua tách nhiệm                       | Thêm khóa vế phải vào vai trò mà một người giữ vế trái → 23514 tách nhiệm; sai nếu phép trả sớm đọc nhầm vế hay bỏ luật miễn trừ được → test đỏ                                                              |

## Tiêu chí chấp nhận

- [ ] K1: test cảnh báo một lần mỗi lần xuống xanh với hai tenant trong một giao dịch; sai nếu thiếu hay thừa một sự
      kiện, và đột biến của K1 làm test đỏ.
- [ ] K2: test hai neo xanh; sai nếu lần ghi đó được nhận, và đột biến của K2 làm test đỏ.
- [ ] K3: test vế phải xanh; sai nếu lần ghi đó được nhận, và đột biến của K3 làm test đỏ.
- [ ] Số đo: `q2` của `make bench-rbac`, lần gán 1.000 người và "thêm 10 khóa, 10 lệnh", trước và sau ở `RESULTS.md`;
      sai nếu không giảm.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `db/migrations/versions/b5677d345bc1_tenant_roles.py:1188-1198`, `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:1038-1089`; spec: R3.12, RB40.
- `db/migrations/versions/d2b57239ef50_role_administration_and_anti_escalation.py:399-435`, `db/migrations/versions/557e6907195e_service_principals_run_as.py:464`; spec: R6.1, R6.3, RB15, RB16.
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:584-628`; spec: R5.1, RB14.
- `db/bench/rbac/RESULTS.md:104-166` (Câu 2), `db/bench/rbac/RESULTS.md:239-254` (Phát hiện 2-4, 6).

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cắt từ Phát hiện 2-4 của discovery/08 cùng lúc với ticket 07, để ba
  việc cần migration không mất; chưa gate. Chờ ticket 07 vì cùng harness và cùng mốc đo (`gc.freeze()` bỏ nhiễu GC khỏi
  số `/me` cạnh lần ghi). Nếu sai thì: tách thành ba ticket, mỗi trigger một.
