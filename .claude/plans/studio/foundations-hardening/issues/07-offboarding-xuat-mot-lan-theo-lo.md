# 07 — Offboarding xuất mỗi dòng một lần, đọc theo lô keyset, xóa theo sổ bước

Status: needs-triage
Blocked by: .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md
Area: studio
Yêu cầu: R11.1, R11.2, R11.3, R11.4, R11.5, G8, FH30, FH31, FH33

## Mục tiêu

Gói xuất của một công ty rời nền tảng có mỗi dòng đúng một lần, kể cả dòng của bảng phân vùng, và lane
`offboarding` đọc mỗi bảng theo lô keyset thay vì giữ cả bảng trong bộ nhớ (R11, G8, FH30, FH31; YC6, D12).
Audit `tenant.offboarding.purged` vẫn đứng tên người vận hành đã yêu cầu và thêm `details.lane` bằng
`offboarding` (R11.3; `CLAUDE.md`, "Agent and tool rules"; ADR-0011 (Accepted)). Bản vá xuất một lần
không dựa vào việc studio-skeleton/01 làm partition không đọc được theo tên dưới `dw_app`, nhưng ticket
này chờ studio-skeleton/01 vì cả hai sửa `offboarding.py` và test của nó: studio-skeleton/01 thêm
`STUDIO_EXCLUSIONS` và test phủ dùng chính hai truy vấn catalog mà ticket này đổi. Mọi ticket khác sửa
`offboarding.py`, danh mục xuất hay `test_offboarding.py` chờ ticket này qua dòng Blocked by của chính nó
(`scripts/check_plans.py --table` in bảng sống), nên `_CATALOG_COLUMNS` và `export_rows` có một thứ tự sửa. Ticket
này cũng thay danh sách tay `_ORDERED_FIRST` và thứ tự các bước xóa mà studio-skeleton/01 khai bằng một sổ bước xóa ở
composition root, thứ tự suy từ khóa ngoại `RESTRICT` và `NO ACTION` của `pg_constraint` (R11.4, R11.5, FH33; H-2), để
org-and-principals/03 và usage-and-limits/02 mỗi bên đăng ký bước của mình mà không chờ nhau.

## Việc cần làm

1. Viết trước test âm `test_a_partitioned_table_is_exported_once` trong
   `packages/python/dw_platform/tests/integration/test_offboarding.py`: một bảng phân vùng thử (theo
   khoảng trên `created_at`, có `tenant_id`, policy `tenant_isolation_*` trên bảng cha và trên từng
   partition, `dw_app` có SELECT trên bảng cha và trên partition), một dòng của tenant ở partition tháng
   và một ở DEFAULT; khẳng định mỗi dòng có đúng một lần trong kết quả xuất. Test phải đỏ trên mã hiện
   có, vì dòng được xuất hai lần; ghi kết quả vào Comments. Bảng thử bị xóa ở teardown, vì test catalog
   của studio-skeleton/01 đỏ với một bảng phân vùng có DEFAULT mà sổ không có dòng (studio-skeleton:R3.4).
2. `SqlTenantOffboarding`: `_CATALOG_COLUMNS` thêm điều kiện `NOT c.relispartition`, nên danh mục xuất
   và danh mục xóa chỉ gồm bảng cha.
3. Đo trước bằng catalog rằng mọi bảng mà danh mục xuất trả có khóa chính (`pg_index.indisprimary`);
   bảng nào không có thì ghi Comments và báo Đạt, không đọc cả bảng trong một câu lệnh.
4. `export_rows` đọc mỗi bảng theo lô keyset trên khóa chính, mỗi câu lệnh có dạng
   `WHERE tenant_id = :t AND (<khóa chính>) > (:cuối lô trước) ORDER BY <khóa chính> LIMIT 1000`;
   khóa chính đọc từ catalog, cả lượt trong một giao dịch như hôm nay. Trả các lô theo bảng thay vì
   một danh sách mọi dòng; `OffboardingStorePort` và `_build_bundle` của lane worker ghi từng lô vào
   mục ndjson của bảng đó.
5. Giữ actor của audit `tenant.offboarding.purged` là người vận hành đã yêu cầu (ADR-0011 (Accepted),
   mục "Not applied"); `_record_purge_audit` ghi `details` là `{"lane": "offboarding"}` thay cho `{}`,
   vì lane thi hành quyết định của một người thì audit người đó và nêu tên mình ở `details.lane`
   (`CLAUDE.md`, "Agent and tool rules").
6. **Sổ bước xóa** (R11.4; H-2). Trong `dw_platform` (adapter offboarding): kiểu `OffboardingPurgeStep` (`name`,
   `tables` là tập `schema.table` mà bước xóa, và hàm chạy bước trong giao dịch xóa) và `OffboardingPurgeSteps`, sổ có
   `register(step)` từ chối tên hay bảng đã có trong sổ (R11.5). Sổ được dựng ở composition root của worker
   (`apps/worker/src/dw_worker/main.py:403-405`) và truyền vào `SqlTenantOffboarding`; không module nào khác dựng sổ.
   Ticket này không đăng ký bước riêng nào: usage-and-limits/02 (`platform.purge_tenant_append_only`) và
   org-and-principals/03 (`platform.purge_tenant_service_users`) đăng ký bước của mình ở cùng chỗ đó.
7. **Bước mặc định.** Mỗi bảng của danh mục xóa (`_CATALOG_PURGEABLE`) mà không bước đăng ký nào khai nhận một bước
   mặc định chạy câu `DELETE ... WHERE tenant_id = :t` của hôm nay; một bảng thêm sau chỉ cần DELETE của `dw_app` để vào
   lượt xóa, không sửa sổ.
8. **Thứ tự suy từ catalog.** `purge_rows` đọc, trong giao dịch xóa, mọi khóa ngoại của `pg_constraint` có `contype = 'f'`
   giữa các bảng mà các bước khai, rồi xếp bước theo các cạnh: với mỗi khóa ngoại `confdeltype` `r` (`RESTRICT`) hay `a`
   (`NO ACTION`) từ bảng C tới bảng P, mọi bước xóa C chạy trước bước xóa P; một bảng C mà không bước nào khai, chỉ mất
   dòng qua `CASCADE` (`confdeltype` `c`) từ bảng của một bước, mang cạnh của nó sang mọi bước mà chuỗi `CASCADE` từ bảng
   của bước tới được C. Cạnh tự trỏ (C bằng P) không vào thứ tự. Hai bước không có cạnh nối thì theo tên bước, để thứ tự
   ổn định giữa hai lần chạy. Có vòng → từ chối trước câu xóa đầu với lỗi nêu tên các khóa ngoại của vòng (R11.5); tenant
   giữ `offboarding`, và yêu cầu offboarding sang `failed` với lỗi đó cho người xem, như mọi lỗi của lượt hôm nay
   (`apps/worker/src/dw_worker/consumers/offboarding.py:196-210`). Gỡ `_ORDERED_FIRST`.
9. **Test phủ đọc sổ.** Test phủ offboarding của studio-skeleton/01 (studio-skeleton:R4.2) đọc thứ tự bước mà
   `purge_rows` suy ra, không đọc danh sách khai tay, và đỏ khi một bước đăng ký đi trái một cạnh `RESTRICT` hay
   `NO ACTION`: chạy purge cho một tenant có dòng ở mọi bảng, bắt câu lệnh bằng sự kiện `before_cursor_execute`, gán mỗi
   câu xóa cho bước đã chạy nó, và đỏ khi một bảng bị xóa trước bảng tham chiếu nó, hay khi một bước làm giảm số dòng
   (đếm dưới vai migrator, trước và sau mỗi bước) của một bảng mà bước đó không khai và không tới được qua `CASCADE`.
   Cạnh `RESTRICT` `platform.run_steps.child_run_id` → `platform.worker_runs` mà telemetry-and-audit/03 tạo
   (telemetry-and-audit:R3.10) vào thứ tự từ catalog khi bảng ra đời, không ai đăng ký gì.
10. Test: test ở bước 1 xanh sau bản vá; bảng thử 2.500 dòng xuất đủ 2.500 dòng, mỗi dòng một lần, qua 3
    câu lệnh đọc mà không câu nào trả quá 1.000 dòng (bắt câu lệnh bằng sự kiện `before_cursor_execute`);
    `apps/worker/tests/unit/test_offboarding_consumer.py` theo chữ ký mới.

## Tiêu chí chấp nhận

- [ ] R11.1 (FH30): `test_a_partitioned_table_is_exported_once` đỏ trên mã trước bản vá (ghi Comments)
      và xanh sau; bỏ điều kiện `NOT c.relispartition` khỏi danh mục thì test đỏ lại.
- [ ] R11.2: bảng thử 2.500 dòng xuất đúng 2.500 dòng qua 3 câu lệnh đọc, câu nào cũng trả không quá
      1.000 dòng; đổi về một câu `SELECT` cho cả bảng thì test đỏ.
- [ ] R11.3 (FH31): sau `purge_rows`, audit `tenant.offboarding.purged` của tenant có `details.lane` bằng
      `offboarding`; ghi lại `details` rỗng thì test đỏ.
- [ ] G8 (FH31): `test_purge_records_an_audit_event_before_deleting_anything` xanh trước và sau thay đổi;
      đổi actor sang `system_actor('offboarding')` thì test đỏ.
- [ ] R11.4 (FH33): hai bảng thử tạo trong giao dịch test, tên xếp theo chữ cái ngược chiều cạnh, nối bằng khóa ngoại
      `ON DELETE RESTRICT` → purge xóa cả hai, bảng tham chiếu trước; cùng ca với `NO ACTION` → như vậy; thay phép suy
      bằng thứ tự chữ cái hay bằng một danh sách cạnh chép tay → lỗi khóa ngoại, test đỏ.
- [ ] R11.4 (FH33): bảng thử C chỉ mất dòng qua `CASCADE` từ bảng A của một bước, C giữ khóa ngoại `RESTRICT` tới bảng P
      của bước khác → bước của A chạy trước bước của P; bỏ phép mang cạnh qua `CASCADE` → lỗi khóa ngoại, test đỏ.
- [ ] R11.4 (FH33): một bước thử khai bảng A mà xóa cả bảng B, tham chiếu bởi bảng của bước khác → test phủ của
      studio-skeleton:R4.2 đỏ, nêu bước và khóa ngoại; khai đúng B → xanh.
- [ ] R11.5 (FH33): đăng ký hai bước khai cùng một bảng → `register` từ chối, nêu bảng; hai bảng thử nối vòng bằng hai
      khóa ngoại `RESTRICT` → purge từ chối trước câu xóa đầu, 0 dòng bị xóa ở mọi bảng, tenant giữ `offboarding`, lỗi
      nêu hai khóa ngoại; gỡ kiểm trùng hay kiểm vòng → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-101`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:103-114`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:162-194`
- `apps/worker/src/dw_worker/main.py:403-405`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:217-247`
- `db/migrations/sql/0013_partition_maintenance.sql:73-76`
- `apps/worker/src/dw_worker/consumers/offboarding.py:142-192`
- `packages/python/dw_platform/tests/integration/test_offboarding.py:287-319`
- `docs/adr/0011-a-background-lane-audits-as-itself.md:44-45`
- spec: R11, G8, FH30, FH33.

## Comments

- 2026-10-25 (agent): lượt h, theo H-2 (quyết định tạm của spec cùng ngày): ticket này thay `_ORDERED_FIRST` và thứ
  tự các bước xóa khai tay bằng sổ bước xóa ở composition root, thứ tự suy từ khóa ngoại `RESTRICT` và `NO ACTION` của
  `pg_constraint` (bước 6-9, R11.4, R11.5, FH33); org-and-principals/03 và usage-and-limits/02 đăng ký bước của mình mà
  không chờ nhau (bảng cạnh của lượt h gỡ org-and-principals/03 <- usage-and-limits/02). Dòng Blocked by không đổi.
