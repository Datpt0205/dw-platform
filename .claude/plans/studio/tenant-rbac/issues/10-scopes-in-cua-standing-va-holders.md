# 10 — `scopes_in` của `_STANDING` và `_HOLDERS` ở cỡ D12: đo trước, chuyển vào FROM chỉ khi số đo cần

Status: ready-for-agent
Blocked by: 07
Area: studio
Yêu cầu: không (chi phí của hai câu đọc R2.2 ngoài đường `/me`, nợ từ MEDIUM (i) của gate ticket 07 và Comments của ticket 08; không đổi câu trả lời nào của spec, R2.2, R2.5 và RB5-RB7 giữ bằng test hiện có cộng test bằng nhau ở đây khi câu đổi)

## Mục tiêu

Ticket 07 chuyển lời gọi `platform.scopes_in` của `_HELD` từ danh sách SELECT vào FROM, nơi PostgreSQL inline hàm SQL
trả tập (người thường 10,4 → 3,0 ms p50 ở cỡ D12). Hai câu khác còn dạng cũ: `_STANDING`
(`packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:510-521`, đọc khi tạo hay sửa
người phụ trách DW, `packages/python/dw_platform/src/dw_platform/application/digital_workers.py:415`, và khi giao việc
cho một người, `packages/python/dw_platform/src/dw_platform/application/work_queue.py:431`) và `_HOLDERS`
(`packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:29-40`). `_HOLDERS` có hai dạng: một
thành viên (`:u` có giá trị; `scopes_of`, `holds`, mỗi request của nhân viên hỗ trợ qua
`packages/python/dw_platform/src/dw_platform/application/support_access.py:861-900` và mỗi lần liệt kê quyền hỗ trợ,
`support_access.py:639`) và cả workspace (`:u` NULL; `holding`, gọi `scopes_in` một lần mỗi thành viên, ở `657ef4c6`
chỉ test gọi). Ticket này đo cả hai câu ở cỡ D12 rồi chỉ đổi câu nào số đo cho thấy cần, với câu trả lời bằng đúng như
trước: cùng tập scope, không scope nào của tenant khác (R2.2).

## Việc cần làm

1. **Đo** (`db/bench/rbac/bench_rbac.py`, một câu hỏi mới `q5`; không sửa `Makefile`, chạy
   `DW_TEST_DB_SUFFIX=_fog38 uv run python db/bench/rbac/bench_rbac.py setup q5 drop`, database xóa sau khi đo). Cùng một
   lần chạy, cùng database, ba cột cho mỗi câu: mốc danh sách SELECT (câu ở `657ef4c6` chép nguyên văn vào bench, cố
   định, để lần chạy sau khi sửa vẫn so được với nó), dạng FROM viết trong bench
   (`ARRAY(SELECT s.key FROM platform.scopes_in(...) AS s(key))`, cùng ba tham số, như `_HELD`,
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:53-56`), và câu của module (nhập
   như `q1` nhập `_HELD`, `bench_rbac.py:82`; trước khi sửa bằng mốc, sau khi sửa bằng dạng FROM). Đo dưới `dw_app`
   gắn tenant như `q1` (`bench_rbac.py:659-698`): mỗi dạng 20 lần làm nóng rồi ít nhất 200 lần, P50/P95/P99 của thời gian
   thực thi (`explain_ms`) và của vòng đi về, cho:
    - `_STANDING` và `_HOLDERS` một thành viên (`people` sai, như `scopes_of` và `holds` gọi): người nặng ở workspace đầu
      trong mười workspace của họ, chủ sở hữu, người thường, mỗi người ở workspace của membership đầu của họ (`HEAVY`,
      `OWNER_1`, `PLAIN`, `bench_rbac.py:105`);
    - `_HOLDERS` cả workspace với `people_only` đúng: workspace của người nặng (25 thành viên theo cách gieo,
      `bench_rbac.py:220-262`) và một workspace `q5` gieo dưới `dw_migrator` với một membership cho mỗi người trong 5.000
      người, mỗi membership một lần gán vai trò `member` ở đó như cách gieo gán `member` (`bench_rbac.py:430`); ở cuối
      `q5`, dưới `dw_migrator` (miễn luật giữ quyền), xóa các lần gán, các membership rồi chính workspace, cả khi `q5` lỗi,
      nên lần chạy sau sửa gặp đúng thế giới đó.
      Kèm kế hoạch `EXPLAIN` của mỗi dạng cho người nặng (dạng cũ có nút `ProjectSet` gọi `platform.scopes_in`).
2. **Quyết định, mỗi câu riêng, ghi ở Comments kèm số**: chuyển một câu vào FROM khi cả hai điều sau đúng: (a) ở ít
   nhất một ô một thành viên của bước 1 (đường có người gọi thật), P50 vòng đi về của dạng FROM thấp hơn dạng danh sách
   SELECT ít nhất 20% và ít nhất 1 ms (vòng đi về gồm cả lập kế hoạch, thứ ticket 07 thấy tăng 8,3 → 10,6 ms; thời gian
   thực thi chỉ ghi cạnh); (b) không ô nào của câu đó (mọi người, mọi dạng) có P95 vòng đi về của dạng FROM tệ hơn quá
   20% (`.claude/rules/latency.md`). Dạng cả workspace không tự quyết (ở `657ef4c6` không code nào ngoài test gọi
   `holding`) nhưng chịu (b); P95 của nó ở 5.000 người trên 300 ms thì ghi ở `RESULTS.md` và Comments, không mở ticket
   khi chưa ai gọi `holding` (agent, theo ủy quyền 31/10/2026; Nếu sai thì: một ticket `needs-triage` của spec này cho
   dạng cả workspace). Không đạt thì câu giữ nguyên và ticket không sửa `packages/`.
3. **Câu được chuyển** (chỉ câu đạt ngưỡng ở bước 2): cột `scopes` thành `ARRAY(SELECT s.key FROM platform.scopes_in(...) AS
s(key))`, cùng ba tham số và cùng thứ tự (`_STANDING`: `:t`, `u.id`, `:w`; `_HOLDERS`: `m.tenant_id`, `m.user_id`,
   `m.workspace_id`). Câu trả lời vẫn là của `platform.scopes_in` (ADR-0104 (Accepted) mục 5): không chiếu scope trong
   Python hay từ grant đã đọc (failure-modes #2). Chú thích trên câu ghi số đo của bước 1, như
   `membership_lookup.py:37-41`. Mọi phần khác của câu (`tenant_members.status = 'active'` của `_STANDING`, `u.kind` và
   `ORDER BY` của `_HOLDERS`) không đổi.
4. **Test bằng nhau** (integration, tệp mới `packages/python/dw_platform/tests/integration/test_scope_reads_scopes_from.py`,
   chỉ khi bước 3 đổi ít nhất một câu), theo dạng của test ticket 07: một tenant với ba dạng người ở cỡ nhỏ (người nặng:
   ba workspace, vai trò có khóa mức `tenant`, `workspace` và `record`, một bộ quyền bổ sung; chủ sở hữu; người thường),
   mỗi membership: `scopes` của câu mới bằng đúng tập của dạng cũ (giữ trong test làm mốc) và bằng `platform.scopes_in`;
   `_HOLDERS` cả workspace trả cùng danh sách người và cùng tập mỗi người; `SqlDwMembershipCheck.standing`,
   `SqlScopeHolders.scopes_of` và `holding` trả như dạng cũ. Test, K1-K3 và đột biến chỉ phủ câu được chuyển (`_STANDING`
   thì cả K3); câu giữ nguyên không có test hay đột biến mới. Ca âm theo K2 dưới đây. Sau khi sửa, chạy lại `q5`: câu của
   module (nay là dạng FROM) so với mốc danh sách SELECT, cùng cách đo. Nếu lần chạy đó có một ô trượt (b) của bước 2,
   chạy thêm hai lần và lấy trung vị ba lần mỗi ô; trung vị vẫn trượt thì trả câu về dạng cũ và ghi "giữ" kèm số.
5. `reviewing-feature-security` (khi bước 3 đổi câu), `mutations/10.yaml` một đột biến mỗi dòng Kiểm soát, không chạy
   `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng tay. Số đo ghi vào `db/bench/rbac/RESULTS.md` (mục
   mới) và Comments ở đây.

Kiểm soát của ticket này, chỉ khi bước 3 đổi câu (mã K chỉ dùng trong ticket; mỗi dòng một đột biến ở
`mutations/10.yaml`):

| #   | Kiểm soát                                 | Test âm                                                                                                                                                                                                                                                                                                                                                              |
| --- | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | Scope hẹp đúng như `platform.scopes_in`   | Ba dạng người, mỗi membership: câu mới = dạng cũ = `platform.scopes_in`. Đột biến, mỗi câu được chuyển một: câu mới đọc khóa từ `platform.effective_grants` không qua phép chiếu (khóa mức `workspace` neo ở workspace khác hiện ra ở người nặng) → test đỏ                                                                                                          |
| K2  | Không scope nào của tenant khác           | Cùng người ở hai tenant, mỗi tenant một vai trò mang khóa riêng, đọc dưới `dw_app` gắn tenant đó: ở A bằng đúng `platform.scopes_in` của A (khác rỗng, có khóa riêng của A) và không có khóa của B, và ngược lại, cho câu được chuyển. Sai nếu lời gọi `scopes_in` nhận tenant khác (tenant của membership kia) → test đỏ; chỉ khẳng định vắng mặt thì không đỏ được |
| K3  | `_STANDING` vẫn giấu người không `active` | Người `suspended` ở công ty: `standing` trả `None`, `is_person_in` trả `False`, như dạng cũ. Sai nếu lần chuyển bỏ phép nối `tenant_members` → test đỏ                                                                                                                                                                                                               |

## Tiêu chí chấp nhận

- [ ] Số đo: P50/P95/P99 thời gian thực thi và vòng đi về của hai dạng mỗi câu, mọi dạng và người ở bước 1, cùng lần chạy,
      cùng máy, ở `RESULTS.md` và Comments, cùng kế hoạch `EXPLAIN` hai dạng cho người nặng; sai nếu thiếu một ô, một ô dưới
      200 lần đo, hay hai dạng đo ở hai lần chạy khác nhau.
- [ ] Quyết định: mỗi câu một dòng Comments "chuyển" hay "giữ" kèm hai P50 và phép so ngưỡng của bước 2; sai nếu một câu
      được chuyển mà không dạng một thành viên nào đạt ngưỡng, một câu đạt ngưỡng mà không được chuyển, hay diff của ticket
      sửa `packages/` khi không câu nào được chuyển.
- [ ] Khi một câu được chuyển, K1: test bằng nhau (`test_scope_reads_scopes_from.py`) xanh cho mọi membership của ba dạng người, và cả hai dạng của `_HOLDERS` khi `_HOLDERS` được chuyển;
      sai nếu một scope thêm hay mất ở bất kỳ membership nào, và đột biến của K1 làm test đỏ.
- [ ] Khi một câu được chuyển, K2: ca hai tenant xanh cho câu đó; sai nếu đọc ở A trả khóa chỉ vai trò ở B cấp (hay ngược
      lại) hay thiếu khóa riêng của chính tenant đó, và đột biến của K2 làm chính test hai tenant đỏ.
- [ ] Khi `_STANDING` được chuyển, K3: ca người `suspended` xanh; sai nếu `standing` trả khác `None`, và đột biến của K3
      làm test đỏ.
- [ ] Khi một câu được chuyển, số đo sau (lần chạy `q5` sau khi sửa): kế hoạch của câu đó không còn nút `ProjectSet`
      hay `Function Scan` trên `platform.scopes_in`, như ticket 07, và ở mọi ô của câu đó P95 vòng đi về không tệ hơn mốc
      danh sách SELECT quá 20%; sai nếu kế hoạch còn một trong hai nút hay một ô tệ hơn quá 20%.
- [ ] Xong: `uv run python -m pytest packages/python/dw_platform/tests/integration/test_scope_holders.py packages/python/dw_platform/tests/integration/test_access_lookup_scopes_from.py packages/python/dw_platform/tests/integration/test_digital_workers_db.py packages/python/dw_platform/tests/integration/test_work_queue_db.py packages/python/dw_platform/tests/integration/test_support_grants.py packages/python/dw_platform/tests/integration/test_support_staff_access.py` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:510-521` (`_STANDING`), `packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:29-40` (`_HOLDERS`), `packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:87-143` (`holding`, `holds`, `scopes_of`).
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:37-56` (dạng FROM của ticket 07 và chú thích số đo); spec: R2.2, R2.5.
- `packages/python/dw_platform/src/dw_platform/application/digital_workers.py:415`, `packages/python/dw_platform/src/dw_platform/application/work_queue.py:431`, `packages/python/dw_platform/src/dw_platform/application/support_access.py:639`, `packages/python/dw_platform/src/dw_platform/application/support_access.py:861-900` (người gọi).
- `db/bench/rbac/bench_rbac.py:82`, `db/bench/rbac/bench_rbac.py:105`, `db/bench/rbac/bench_rbac.py:220-262`, `db/bench/rbac/bench_rbac.py:659-698`; `db/bench/rbac/RESULTS.md` (mục "Đo lại sau tenant-rbac/07").
- Comments của ticket 07 (MEDIUM (i)) và ticket 08 (dòng `_STANDING` và `_HOLDERS`, 5/11/2026); ADR-0104 (Accepted) mục 5; `.claude/rules/latency.md`.

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cắt từ dòng `_STANDING`/`_HOLDERS` trong Comments của ticket 08 (gate
  ticket 07, MEDIUM (i)). `_STANDING` nằm ở `digital_workers_repo.py`, không ở `membership_lookup.py`. Đọc lại ở head:
  dạng cả workspace của `_HOLDERS`, dạng gọi `scopes_in` một lần mỗi thành viên, không có người gọi ngoài test; đường
  có người gọi thật là dạng một thành viên, cùng hình với `_HELD` trước ticket 07, nên ngưỡng quyết định đặt trên dạng
  đó. `Blocked by: 07` vì dùng dạng FROM và test bằng nhau của nó; không phụ thuộc 08 hay 09, nhưng không dựng cạnh
  ticket 08: cả hai ghi `db/bench/rbac/RESULTS.md` và dùng database `dw_bench_rbac_fog38`. Nếu sai thì: (1) ngưỡng
  20% và 1 ms hẹp quá thì chuyển cả hai câu vì một dạng cho mọi câu đọc `scopes_in` (chú thích của
  `membership_lookup.py` đã nói "never in a SELECT list"), cùng test; (2) `holding` có người gọi thì dạng cả workspace
  quyết như dạng một thành viên.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check: không migration, không
  route). Ba HIGH, sửa ở ticket. (1) Đột biến K1 của `_HOLDERS` ("tham số workspace thành `:w`") tương đương code gốc, vì
  `WHERE m.workspace_id = :w`; nay mỗi câu được chuyển một đột biến đọc khóa không qua phép chiếu. (2) Ngưỡng đặt trên
  thời gian thực thi, bỏ qua lập kế hoạch (ticket 07 thấy 8,3 → 10,6 ms), nên một câu "đạt" có thể chậm hơn ở request
  thật; ngưỡng nay trên P50 vòng đi về. (3) Luật 20% của `latency.md` chỉ áp cho dạng cả workspace; nay là điều kiện (b)
  của bước 2 cho mọi ô của câu, trước và sau sửa. MEDIUM, sửa: mốc danh sách SELECT chép nguyên văn vào bench để lần chạy
  sau sửa so được; kế hoạch cấm cả `Function Scan` như ticket 07; lệnh Xong thêm bốn tệp test phủ `_STANDING` và
  `scopes_of`; P95 cả workspace trên 300 ms chỉ ghi số khi chưa ai gọi `holding`. Nếu sai thì: lỗi lộ ra khi dựng, ghi
  ở đây.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới, builder check): 0 CRITICAL, 0 HIGH.
  MEDIUM, sửa ở thân: lần chạy sau sửa trượt (b) thì trung vị ba lần, vẫn trượt thì trả về và ghi "giữ"; workspace 5.000
  người có lần gán `member` ở đó và được dọn cả khi `q5` lỗi; ô một thành viên đo với `people` sai như `scopes_of`, ở
  workspace đầu của mỗi người; test và đột biến chỉ phủ câu được chuyển. MEDIUM, không sửa: điều kiện (b) cho phép dạng
  cả workspace, chưa ai gọi, chặn lần chuyển một câu nhanh hơn ở dạng một thành viên; giữ vì `holding` dùng chung câu đó
  và người gọi đầu tiên của nó sẽ thừa hưởng; Nếu sai thì: (b) chỉ xét ô có người gọi. Sửa sau lượt xác nhận không được
  người đọc mới đọc lại.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
