# 07 — Đuôi `GET /api/v1/me` ở cỡ D12: `gc.freeze()` khi API khởi động, `scopes_in` trong FROM

Status: ready-for-agent
Blocked by: 02, 04
Area: studio
Yêu cầu: không (chi phí của đường đọc R2.2 theo hai phát hiện của discovery/08, ngân sách tạm của `.claude/rules/latency.md`; không đổi câu trả lời nào của spec, R2.2, R2.4, R2.5 và RB5-RB7 giữ bằng test hiện có cộng test bằng nhau ở đây)

## Mục tiêu

discovery/08 (FOG-38) đo `GET /api/v1/me` ở một công ty 5.000 người và thấy hai chỗ tốn không đổi câu trả lời nào: mọi
lần P95 trượt 300 ms (311 ms cạnh một lần sửa vai trò, 328-433 ms không cache) là GC thế hệ 2 của Python dừng khoảng
241 ms mỗi lần, và câu dựng AccessContext (`_HELD`) tốn 28 ms p50 so với 6,7 ms của `platform.effective_grants` vì gọi
`platform.scopes_in` trong danh sách SELECT, nơi PostgreSQL không inline hàm SQL trả tập. Ticket này đưa heap lúc khởi
động của API ra khỏi bộ thu gom và chuyển lời gọi `scopes_in` vào FROM, rồi đo lại bằng `make bench-rbac`, để người dùng
có quyền nặng (30 vai trò ở 10 workspace) và chủ sở hữu nhận `/me` trong ngân sách ở mọi ô, kể cả cạnh một lần ghi quyền
lớn, trừ ô mà số đo chỉ ra nguyên nhân ngoài hai chỗ này (ghi kèm ticket sở hữu nó). AccessContext phải hẹp đúng như trước (R2.2): cùng tập quyền, cùng vai trò, cùng grant, không quyền nào của tenant
khác.

## Việc cần làm

1. **`gc.freeze()` trong lifespan của API** (`apps/api/src/dw_api/main.py:160-170`): sau khi container đã dựng
   (`create_app` nhận nó) và sau `container.run_events.start()`, trước `yield`, gọi `gc.collect()` rồi `gc.freeze()`
   đúng một lần, để rác của lúc khởi động không bị đóng băng cùng heap sống; ở `finally`, sau `container.shutdown()`,
   gọi `gc.unfreeze()`, để một tiến trình dựng nhiều app (test, harness) không giữ mãi rác vòng của app đã tắt.
   `create_app` không gọi gì của `gc`: route và middleware chưa dựng xong ở đó. Không cờ cấu hình nào: một cờ chỉ
   test đọc là failure-modes #1, và `uat`/`production` chạy như nhau.
2. **Worker: đo, không sửa.** Đo một lần thu gom đầy đủ trong tiến trình worker sau khi registry dựng xong (thời gian
   `gc.collect()` khi heap không đóng băng và khi đã đóng băng, cùng cách đo cho API) và ghi số ở Comments. Ticket này
   không sửa `apps/worker`: worker không có ngân sách request, và `apps/worker/src/dw_worker/main.py` thuộc làn build
   khác. Quyết định ghi ở Comments kèm số, không suy từ số của API, và là một trong hai: đường dẫn một ticket
   `needs-triage` mới của spec này (`gc.freeze()` khi worker khởi động, thêm vào "Danh sách ticket" qua
   `writing-plan-specs`), hay lý do số đo cho thấy không cần.
3. **`scopes_in` trong FROM** (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:44-62`):
   cột `scopes` của `_HELD` thành `ARRAY(SELECT s.key FROM platform.scopes_in(...) AS s(key))`, cùng ba tham số; cùng
   cách cho `_SCOPES_IN` (`membership_lookup.py:37-39`, người đọc của `effective_scopes`). Câu trả lời vẫn là của
   `platform.scopes_in` (ADR-0104 (Accepted) mục 5): không chiếu scope trong Python hay trong câu này từ grant đã đọc, vì
   đó là bản thứ hai của luật chiếu (failure-modes #2). `_STANDING` (`digital_workers_repo.py:511-521`) và `_HOLDERS`
   (`scope_holders.py:29-40`) cùng dạng nhưng không nằm trên đường `/me`: ngoài ticket này, ghi ở Comments.
4. **Test bằng nhau** (integration, `packages/python/dw_platform/tests/integration/`): một tenant theo ba dạng của bench
   ở cỡ nhỏ (người nặng: ba workspace, vai trò có khóa mức `tenant`, `workspace` và `record`, một bộ quyền bổ sung; chủ
   sở hữu `tenant_owner`; người thường chỉ `member`), mỗi membership của mỗi người: `scopes` của `_HELD` mới bằng đúng
   tập của dạng cũ (câu cũ giữ trong test làm mốc) và bằng `platform.scopes_in`, `role_keys` và `grants` không đổi;
   `SqlMembershipLookup.find_access` trả cùng AccessContext. Ca âm: cùng người là thành viên một tenant thứ hai với vai
   trò mang khóa riêng; dựng dưới `dw_app` gắn tenant đó như `_access_in` chạy, lần dựng ở mỗi tenant bằng đúng
   `platform.scopes_in` của tenant ấy (khác rỗng, có khóa riêng của nó) và không có khóa nào của tenant kia. Chỉ khẳng
   định vắng mặt thì không đỏ được: RLS dưới `dw_app` giấu dòng của tenant kia, nên lời gọi nhận tenant sai trả rỗng chứ
   không lộ khóa.
5. **Test lifespan** (unit, `apps/api/tests/unit/`): ghi thứ tự các lời gọi `run_events.start`, `gc.collect`,
   `gc.freeze`, `gc.unfreeze` qua `LifespanManager`.
6. **Đo** (`make bench-rbac`, `DW_TEST_DB_SUFFIX=_fog38`, database xóa sau khi đo): các ô `/me` của `q1`, `q1gc`, `q2`
   (cache nóng, ngay sau tăng version, không cache, cạnh lần gán 1.000 người và các lần sửa vai trò) và thời gian
   `_HELD` của `q1`, trước (bản xuất của commit gốc) và sau, cùng máy, cùng cách; kế hoạch `EXPLAIN` của `_HELD` cho người
   nặng trước và sau. Ghi P50/P95/P99 vào `db/bench/rbac/RESULTS.md` và Comments ở đây; một ô trượt ghi đúng số.
7. `reviewing-feature-security` (một câu phân quyền đổi), `mutations/07.yaml` một đột biến mỗi dòng Kiểm soát, không
   chạy `scripts/mutate.py` (để lúc đóng hàng đợi); phá thử một mẫu bằng tay.

Kiểm soát của ticket này (mã K chỉ dùng trong ticket; mỗi dòng một đột biến ở `mutations/07.yaml`):

| #   | Kiểm soát                                             | Test âm                                                                                                                                                                                                                                                                                                             |
| --- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | AccessContext hẹp đúng như `platform.scopes_in`       | Ba dạng, mỗi membership: `scopes` mới = tập cũ = `platform.scopes_in`. Sai nếu câu mới đọc khóa từ `effective_grants` không qua phép chiếu (khóa mức `workspace` neo ở workspace khác hiện ra ở người nặng) → test đỏ                                                                                               |
| K2  | Không quyền nào của tenant khác                       | Cùng người ở hai tenant, mỗi tenant một vai trò mang khóa riêng, dựng dưới `dw_app` gắn tenant đó: dựng ở A bằng đúng `platform.scopes_in` của A (có khóa riêng của A) và không có khóa của B, và ngược lại. Sai nếu lời gọi `scopes_in` nhận tenant khác `:t` (tenant của membership kia của cùng người) → test đỏ |
| K3  | Đóng băng một lần, sau khi container và app dựng xong | `create_app` không gọi `gc.freeze`; vào lifespan: `run_events.start` → `gc.collect` → `gc.freeze`, mỗi thứ đúng một lần; ra: `gc.unfreeze`. Sai nếu bỏ `gc.freeze`, gọi nó trước `gc.collect`, hay chuyển nó vào thân `create_app` → test đỏ                                                                        |

## Tiêu chí chấp nhận

- [ ] K1: test bằng nhau xanh cho người nặng (mỗi workspace của họ), chủ sở hữu và người thường, gồm `role_keys`,
      `grants` và AccessContext của `find_access`; sai nếu một khóa thêm hay mất ở bất kỳ membership nào, và đột biến của
      K1 làm test đỏ.
- [ ] K2: ca hai tenant xanh; sai nếu dựng ở A trả bất kỳ khóa nào chỉ vai trò ở B cấp (hay ngược lại), hay thiếu khóa
      riêng của chính tenant đó, và đột biến của K2 làm chính test hai tenant đỏ.
- [ ] K3: test lifespan xanh với thứ tự `run_events.start`, `gc.collect`, `gc.freeze` khi vào và `gc.unfreeze` khi ra,
      mỗi thứ một lần; sai nếu `create_app` một mình đã gọi `gc`, hay một trong ba đột biến của K3 vẫn xanh.
- [ ] Số đo: `_HELD` của người nặng thực thi p50 dưới 28,1 ms của commit gốc, đo cùng lần chạy, và kế hoạch sau không
      còn lời gọi `scopes_in` như một hàm riêng (nút `Function Scan` hay `ProjectSet` trên `platform.scopes_in`); sai nếu
      p50 không giảm hay kế hoạch còn nút đó.
- [ ] Số đo: mọi ô `/me` của `q1` và `q2` (cache nóng, sau tăng version, không cache, cạnh lần ghi), cả ba người,
      P95 ≤ 300 ms và P99 ≤ 1 s sau sửa, trước và sau ghi ở `RESULTS.md` và Comments. Một ô trượt chỉ được nhận khi số đo
      chỉ ra nguyên nhân ngoài hai thay đổi của ticket này (GC của API, `_HELD`), ghi số, nguyên nhân và ticket sở hữu nó
      (ticket 08 hay một ticket mới); sai nếu một ô trượt vì GC hay `_HELD`, trượt mà thiếu số, nguyên nhân hay chủ, hay
      P95 sau tệ hơn trước quá 20% mà không có lý do (`.claude/rules/latency.md`).
- [ ] Worker (bước 2): thời gian `gc.collect()` trong tiến trình worker, không đóng băng và đóng băng, ghi ở Comments
      cùng quyết định (đường dẫn ticket mới hay lý do không cần); sai nếu thiếu một trong hai số hay quyết định, hay diff
      của ticket này sửa `apps/worker`.
- [ ] Xong: `uv run python -m pytest apps/api/tests/unit/test_gc_freeze_at_startup.py packages/python/dw_platform/tests/integration/test_access_lookup_scopes_from.py` xanh.

## Nguồn

- `apps/api/src/dw_api/main.py:160-170` (lifespan).
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:37-39`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:44-62`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:159-175`; spec: R2.2.
- `db/migrations/versions/ef68083f2905_object_and_field_privileges_in_roles.py:325-338` (`platform.scopes_in`, LANGUAGE sql STABLE, inline được trong FROM); `db/migrations/versions/b5677d345bc1_tenant_roles.py:403-416` (`platform.effective_grants`).
- `db/bench/rbac/RESULTS.md:93-102` (GC và `_HELD`), `db/bench/rbac/RESULTS.md:239-251` (Phát hiện 1 và 5); `db/bench/rbac/bench_rbac.py:1562-1599` (`q1gc`).
- `.claude/plans/studio/discovery/issues/08-rbac-cost.md` (`## Answer`); ADR-0104 (Accepted) Open 6 (trả lời 5/11/2026); `.claude/rules/latency.md` (ngân sách).

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cắt từ Phát hiện 1 và 5 của discovery/08; ba phát hiện cần migration
  (2-4) là ticket 08, `needs-triage`. Đặt ở tenant-rbac vì cả hai sửa đường đọc R2.2 mà spec này sở hữu (AccessContext,
  `/me`) và discovery/08 mở khóa spec này; không ở runtime-hardening, spec đó giữ cửa công cụ, biên mạng, run và
  outbox. `Yêu cầu: không (...)` vì không mã R nào nói về chi phí; R2.2 và RB5-RB7 là thứ phải giữ, không phải thứ ticket
  này làm đúng. Nếu sai thì: thêm một yêu cầu chi phí (R10) vào spec qua `writing-plan-specs`, và ticket dẫn mã đó.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check), ba HIGH sửa ở ticket.
  (1) Ca âm K2 chỉ khẳng định vắng mặt thì không đỏ được dưới `dw_app`: RLS giấu dòng tenant kia, nên `scopes_in` nhận
  tenant sai trả rỗng; ca hai tenant nay khẳng định thêm mỗi tenant bằng đúng `platform.scopes_in` của nó, khác rỗng
  (bước 4, K2, tiêu chí K2). (2) Bước 2 để "làm ở đây hay ticket sau" mà không tiêu chí nào kiểm, và `apps/worker` thuộc
  làn khác: ticket chỉ đo, không sửa worker, quyết định là một ticket `needs-triage` mới hay lý do không cần, có tiêu
  chí riêng. (3) `Mục tiêu` đòi mọi ô `/me` trong ngân sách mà tiêu chí nhận mọi ô trượt có ghi số: ô trượt chỉ được nhận
  khi nguyên nhân đo được ngoài GC và `_HELD`, ghi chủ, cộng luật 20% của `latency.md`. Nếu sai thì: (1) K2 chạy dưới
  `dw_migrator` để lộ khóa thật hiện ra; (2) ticket sửa worker khi làn kia xong; (3) ô trượt nào ghi số cũng nhận.
- 2026-11-05 (agent): gate, MEDIUM và LOW, không sửa, người dựng quyết khi làm. MEDIUM: (a) "commit gốc" chưa định nghĩa
  và bench nhập `_HELD` từ module: khuyến nghị "trước" là commit ngay trước commit đầu của ticket này, chạy trên bản
  `git archive` cùng phiên máy, 28,1 ms chỉ là số tham chiếu; (b) `latency.md` dời đo độ trễ tới lúc đóng hàng đợi: bench ở
  đây là bằng chứng chấp nhận của chính ticket (mục đích duy nhất của nó là chi phí), không thay lượt đo lúc đóng hàng đợi;
  (c) sau bước 1 pha `default` của `q1gc` đã đóng băng: ghi rõ ở `RESULTS.md`, không đọc nó như mốc chưa đóng băng; (d)
  bước 1 viết `gc.unfreeze()` sau `container.shutdown()`: gọi trước (hay trong `finally` lồng) để một lần tắt lỗi vẫn
  tan băng; (e) `container.run_events is None` vẫn `gc.collect()` rồi `gc.freeze()`, test K3 phủ cả nhánh đó; (f) bước 2
  chưa nói cách đo và ngưỡng cho worker: đo bằng `gc.callbacks` qua một chu kỳ lane như `q1gc`, script ngoài `apps/worker`;
  (g) "`find_access` trả cùng AccessContext" so với AccessContext dựng từ câu `_HELD` cũ, không với chính câu mới; (h) ô
  `/me` của `q1`, `q2` không bấm giờ GC hay `_HELD`: nguyên nhân một ô trượt lấy từ `q1gc` và thời gian `_HELD`; (i)
  `_STANDING`, `_HOLDERS` dời mà chưa có chủ: ghi vào ticket 08 khi gate nó hay mở ticket mới. LOW: (j) hai app sống cùng
  tiến trình thì app tắt trước tan băng heap của app kia (chỉ test, harness); (k) đột biến K2 dưới RLS cho tenant NULL,
  không phải tenant B; (l) fixture nên có một khóa bản ghi sinh ra ngoài danh mục để phủ nhánh
  `coalesce(k.scope_kind, 'record')`.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
