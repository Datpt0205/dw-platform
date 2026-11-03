# 01 — Đo hình dạng RLS cho quyền trên bản ghi trước khi khóa thiết kế

Status: ready-for-agent
Blocked by: .claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R9.4, R9.5, R9.6, R9.7, R9.8, R9.9

## Mục tiêu

Mẫu policy của ticket 03 chỉ được khóa khi đã đo ở quy mô D12. Ticket này dựng các biến thể chính sách cho bộ policy
RESTRICTIVE tenant cộng PERMISSIVE theo lệnh của ADR-0105 (Accepted) mục 1, với đủ sáu nhánh tầm (mặc định toàn tenant,
khóa workspace, của tôi, của nhóm, cấp dưới, khóa chia sẻ) dù W1 chỉ dùng ba, để W2 thêm nhánh mà không đổi hình, và
chạy chúng ở `--scale smoke` trên máy dev. Ticket đo trên đúng harness, seed và tải của custom-objects/01, chủ duy nhất
của chúng, cùng đủ chỉ mục slot của biến thể A1, và chỉ thêm biến thể chính sách (V4.32; ADR-0105 (Accepted)
Consequences; ADR-0107 (Accepted) quyết 2). Lần chạy `--scale d12` trên máy tham chiếu, nơi các ngưỡng R9 được xét và
số vào ADR-0105 (Accepted), là ticket 06 (`ready-for-human`, Chờ Đạt 23).

## Việc cần làm

1. Mã ở trong harness của custom-objects/01, không cạnh nó: một mô-đun biến thể chính sách trong gói
   `scripts/bench_records_storage/records_bench/` (chỗ docstring của `scripts/bench_records_storage.py` dành cho nó),
   test của nó dưới `records_bench/tests/`, một tùy chọn của chính `scripts/bench_records_storage.py` chọn biến thể chính
   sách, và target `make bench-record-access SCALE=<smoke|d12> MODULUS=<8|4>` gọi
   `uv run python scripts/bench_records_storage.py --scale $(SCALE) --moduli $(MODULUS)` với tùy chọn đó. Lần chạy
   này chỉ dựng ô chính sách (DDL A1 cộng phần thay của bước 2), ở một modulus, và chỉ chạy các phép đo của bước 5: không chạy ô A1 của
   custom-objects/01 hay các phép đo lưu trữ của nó (planning, q-error, HOT, nhập, Campaign, promote), và luật đủ ô của
   lần chạy này là ma trận bước 2 và 5 ở modulus đó, không phải "mỗi biến thể có số ở cả hai modulus" của harness. Không
   schema nháp riêng, không bộ gieo riêng, không chép harness: DDL A1, `seed(scale)`, tải, đường ghi mô phỏng, báo cáo,
   container riêng và việc dọn `dw_bench` là của harness và dùng không đổi; harness chỉ nhận thêm nhánh chạy ô chính
   sách và một câu lệnh tùy chọn chạy sau phần gắn setting của `scope_sql` trong cùng giao dịch (lời gọi cửa sổ tầm của
   bước 5), mà ô của custom-objects/01 không đặt nên số của nó không đổi.
2. Mỗi biến thể chính sách là A1 cộng một phần thay khai báo trong mô-đun đó, và chỉ được thay: các policy trên
   `studio.records` và partition; sổ tầm `studio.principal_scopes`, `studio.access_epochs`, các hàm `studio.acl_*`,
   `studio.compute_principal_scope()`, `studio.ensure_principal_scope()` và trigger đánh dấu `stale` hay tăng epoch, thay
   bản thay tối thiểu của harness; bản thay `studio.actor_boundaries` (một danh sách object cho mỗi `app.boundary_id`,
   ADR-0103 (Accepted)) và bản thay của `studio.assign_record`, `studio.share_record` (bước 5); với trục kiểu khóa, cột
   sinh `access_key`, chỉ mục của nó và cột số thứ tự theo tenant trên `studio.object_defs` và bảng workspace mà khóa
   `bigint` ghép từ đó. Hàm `studio.acl_*` là `LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định, trả mảng
   rỗng khi thiếu; mọi setting và mảng đọc ở dạng `(SELECT f())::uuid[]`; có nhánh loại actor, giới hạn dữ liệu (theo
   `app.boundary_id`; hồ sơ agent chạy dưới danh nghĩa người của hồ sơ Toàn công ty với giới hạn `mkt_lead`, nên tầm của
   nó bằng mảng `objects:tenant [mkt_lead]` mà harness cho chủ thể agent; người ghi `workflow` của tải với giới hạn mọi
   object) và điều kiện hết hạn trên `grants_valid_until` của ADR-0105 (Accepted) quyết 3.
    - Mốc P0 là ADR-0105 (Accepted) đúng như viết: `access_key` `uuid` từ md5 của object và workspace sở hữu; sổ tầm một
      dòng mỗi chủ thể, PK `(tenant_id, principal_id)`, `epoch`, `version`, `state`, một mảng cho mỗi hành động và nhánh
      (quyết 4); nhánh đọc mảng khóa bằng `= ANY` và `&&`; không câu gợi ý cho planner.
    - Bốn trục, mỗi trục đổi một điều quanh P0: khóa `bigint` ghép hai số nhỏ theo tenant; sổ tầm một dòng cho mỗi
      hành động; nhánh viết bằng join bảng sổ tầm hay `EXISTS` thay mảng; có câu gợi ý cho planner. Câu gợi ý không nằm
      trong policy: nó là bộ lọc "Của tôi" mà trang danh sách gửi, `AND owner_id = (SELECT studio.acl_user())`, chỉ ở
      truy vấn trang của hai hồ sơ Của tôi (`own`, `own_sort_slot`), so với cùng hai hồ sơ có bộ lọc đó bằng tham số; trình
      dựng truy vấn của harness nhận một vị từ tùy chọn mà chỉ ô chính sách đặt.
    - Mỗi phương án của mỗi trục là một ô đủ: R9.1 tới R9.4 và R9.6 tới R9.9 ở mọi hồ sơ, nóng và nguội; R9.5 (soak) chỉ
      ở P0 và tổ hợp thắng. Phương án thắng của một trục là phương án đạt mọi ngưỡng của ô đó ở mọi hồ sơ, với "p95 tệ nhất" thấp nhất, tức p95 lớn nhất của trang đầu R9.1 qua mọi hồ sơ, nóng và
      nguội, hai object của bước 3 và có hay không bộ lọc; không phương án nào đạt thì phương án có p95 tệ nhất thấp
      nhất, ghi "trượt"; chênh dưới 10% thì giữ P0. Ngưỡng là ngưỡng R9 ở cả hai scale: ở smoke kết quả chỉ chọn
      phương án cho ticket 02, 03 đọc, ticket 06 chọn lại ở D12. Tổ hợp các phương án thắng đo thêm một lần đủ mọi phép
      đo của bước 5, vì các trục có thể tương tác.
    - Modulus là `MODULUS` của lệnh (mặc định của target là 8), lấy từ dòng luật quyết bước 7 trong Comments của
      custom-objects/01 cho cùng scale; Comments chưa có dòng đó thì 8, ghi vào `RESULTS.md` là chưa chọn.
3. Dữ liệu là seed T1, T2 và 98 tenant nhỏ của custom-objects/01, gồm 300 nhóm, cây quản lý sâu 8, 50 phiên bản quy tắc
   chia sẻ khớp 10% lead và tài khoản dịch vụ sở hữu 10^6 lead. Chia sẻ tay của seed là một quần thể với hai mật độ:
   0,4% bản ghi mọi object và 5% `mkt_lead` (`seed.py`, cột `read_grants`), nên hai mật độ là hai object đo trong cùng
   seed (`mkt_lead` và một object khác), không phải hai lần gieo. Sau `seed(scale)` và bằng cùng hạt giống, mô-đun chỉ
   thêm: dòng sổ tầm; đầu vào mà `studio.compute_principal_scope()` đọc và seed chưa có, là một bản thay theo hình
   `platform.effective_grants` của ADR-0104 (Accepted) mục 5 cho mọi chủ thể mà tải và các phép đo của harness gắn, ở
   mọi tenant, dẫn từ tổ chức của seed: chủ thể hồ sơ giữ đúng các quyền mà `profiles_and_scopes` của harness cho nó,
   cộng quyền giao và chia sẻ mức Toàn công ty trên mọi object cho người của hồ sơ Toàn công ty, người gọi lần giao và
   chia sẻ của bước 5; mọi người khác giữ quyền đọc, sửa và tạo mức Của tôi trên mọi object neo ở workspace nhà (như
   `own_everywhere` của harness). Hàm tính theo ADR-0105 (Accepted) quyết 2 đủ, nên một người có cấp dưới trong cây quản
   lý cũng có nhánh cấp dưới dù hồ sơ của nó là Của tôi; `RESULTS.md` ghi tầm tính được của mỗi hồ sơ; dòng của `studio.actor_boundaries` cho hồ sơ agent và người ghi `workflow`; và `grants_valid_until` ở quá
   khứ trên 1% bản ghi có `read_grants` của T1 (cố định theo hạt giống), NULL ở phần còn lại. Không gieo bản ghi, người,
   nhóm hay workspace nào.
    - Seed đặt `mkt_lead` của T1 ở `public_read` (`records_bench/cell.py`, `_seed_definitions`), nên theo R2.2 mọi người
      giữ quyền đọc lead thấy mọi lead. Ô chính sách đo hồ sơ `public_read` với `default_access = 'public_read'` và mọi hồ
      sơ khác với `'private'` trên `mkt_lead`, đổi giữa hai pha bằng một UPDATE của dòng `studio.object_defs` cùng một lần
      tăng epoch, như lần phát hành phiên bản object làm (R5.2); hàm tính sổ tầm theo R2.2 ở cả hai pha.
4. Hồ sơ quyền là danh sách của custom-objects/01 (Của tôi; Của nhóm tôi; Workspace của tôi; Workspace của tôi và cấp
   dưới trên 40 workspace; Toàn công ty; `public_read` trên `mkt_lead`; quản lý có 50, 500 và 5.000 cấp dưới; người nhận
   500 chia sẻ; agent có giới hạn dữ liệu một object; tài khoản dịch vụ tiếp nhận).
5. Dưới tải hỗn hợp của custom-objects/01 (50 phiên, 80/15/5, lần chạy nguội của nó), đo cho mỗi hồ sơ và mỗi biến
   thể chính sách p50, p95, p99 trên ít nhất 1.000 mẫu, nóng và nguội, kèm `EXPLAIN (ANALYZE, BUFFERS)`: trang đầu 50
   dòng có và không có bộ lọc trên cột slot kiểu, trên `mkt_lead` và trên object 0,4% của bước 3; trang keyset kế tiếp;
   tra một bản ghi theo id; đếm có trần `LIMIT 1001`; INSERT và UPDATE một cột slot qua đường ghi mô phỏng của harness;
   giao (đổi người phụ trách và workspace sở hữu) và chia sẻ qua bản thay SECURITY DEFINER của `studio.assign_record`
   và `studio.share_record`, mỗi lần trong một giao dịch của đường ghi mô phỏng (khóa advisory, `schema_version`, câu
   UPDATE, tăng `version`, một dòng `platform.outbox_events` và một dòng `platform.audit_events`, R8.7, R8.8); DELETE.
   Soak của harness ở 200 lần ghi mỗi giây (R9.5 dưới WITH CHECK; 2 giờ ở d12, `soak_seconds` của scale ở smoke) chỉ chạy trên P0 và tổ hợp thắng. Cộng: thời gian tính sổ tầm
   một chủ thể; cửa sổ tầm khi dòng còn hiệu lực; tính lại 5.000 chủ thể sau một lần tăng epoch; một thu hồi commit giữa
   hai câu lệnh đọc trên hai kết nối; hành vi cắt partition và InitPlan dưới RESTRICTIVE cộng PERMISSIVE.
    - Mỗi độ trễ là thời gian giao dịch đo từ harness trên cùng máy với PostgreSQL, như harness đo
      (`records_bench/run.py`, dòng cấu hình "một vòng khứ hồi"), gồm gắn setting và lời gọi
      `studio.ensure_principal_scope()` mà mọi giao dịch Studio chạy (ADR-0105 (Accepted) quyết 4); vì vậy nó là cận
      trên của thời gian phía máy chủ.
    - R9.7 là một lời gọi cửa trên dòng `stale` trong giao dịch riêng; R9.8 là lời gọi cửa trên dòng `valid`; R9.9 là
      thời gian đồng hồ từ commit tăng epoch tới khi đủ 5.000 dòng `valid`, bốn kết nối gọi cửa lần lượt cho từng chủ
      thể, trong lúc tải hỗn hợp chạy; ghi thêm số của một kết nối.
6. Báo cáo của harness có thêm bảng biến thể chính sách. Ghi máy, phiên bản, cấu hình `postgresql.conf` khác mặc định,
   số đo và kế hoạch vào `db/bench/record-access/RESULTS.md` dưới tiêu đề "smoke, máy dev, không phải số D12", và vào
   Comments. Ticket này không ghi số nào vào ADR-0105 (Accepted): đó là việc của ticket 06 với số D12.
7. Tự kiểm trong script: thoát mã khác 0 khi một phiên không gắn tenant, không gắn loại actor, không có dòng sổ tầm,
   mang epoch cũ, hay chạy trên một policy tạo hỏng mà vẫn ra dòng; khi một dòng của T2 xuất hiện trong phiên của T1;
   khi người nhận chia sẻ đọc được một bản ghi có `grants_valid_until` ở quá khứ chỉ qua nhánh chia sẻ; khi catalog của
   một biến thể khác DDL A1 của custom-objects/01 ngoài phần thay đã khai ở bước 2 (kể cả khi trỏ vào A0); khi mảng mà
   `studio.compute_principal_scope()` tính cho một chủ thể hồ sơ khác mảng của `profiles_and_scopes` ở pha của bước 3
   có cùng `default_access`, so từng cặp (hành động, nhánh) mà `profiles_and_scopes` đặt, nhánh nó không đặt chỉ ghi
   vào báo cáo, và ở trục `bigint` sau khi đổi khóa `uuid` của harness sang `bigint` bằng cùng cột số thứ tự; và khi
   một ô của ma trận bước 2 và 5 thiếu số. Như bước 6 của custom-objects/01, một ngưỡng trượt không làm script thoát khác 0 mà
   thành dòng "trượt" trong bảng số.

## Tiêu chí chấp nhận

- [ ] R9.1: `make bench-record-access SCALE=smoke` trên máy dev, trong container riêng của harness, ghi vào `RESULTS.md`
      trang đầu 50 dòng có và không có bộ lọc, trên `mkt_lead` và object 0,4%, cho mọi hồ sơ của bước 4 và mọi biến thể
      của bước 2 (P0, mỗi phương án của bốn trục, tổ hợp thắng), nóng và nguội, mỗi p95 trên ít nhất 1.000 mẫu với
      `EXPLAIN (ANALYZE, BUFFERS)`, cạnh 50 ms với "đạt" hay "trượt"; sai nếu một số đo trên seed, DDL hay tải khác của
      custom-objects/01, hay `RESULTS.md` hoặc ADR-0105 (Accepted) trình một số smoke như số D12.
- [ ] R9.1: tự kiểm của bước 7 thoát khác 0 khi bỏ mệnh đề tenant khỏi policy RESTRICTIVE (kiểm chéo tenant đỏ), khi bỏ
      điều kiện `grants_valid_until` khỏi nhánh chia sẻ (kiểm hết hạn đỏ), khi trỏ biến thể chính sách vào DDL A0 và khi
      một biến thể thêm một chỉ mục ngoài phần thay đã khai; lần chạy ghi trong Comments.
- [ ] R9.1: đặt ngưỡng trang đầu 0 ms → script vẫn thoát 0 và bảng ghi dòng đó "trượt"; bỏ số của một biến thể chính
      sách → script thoát khác 0.
- [ ] R9.2: tra một bản ghi theo id ở mọi hồ sơ, kể cả tài khoản dịch vụ sở hữu lead, có p95 cạnh 5 ms trong
      `RESULTS.md`; sai nếu thời gian không gồm lời gọi cửa sổ tầm.
- [ ] R9.3: trang keyset kế tiếp ở mọi hồ sơ có p95 cạnh 50 ms.
- [ ] R9.4: đếm có trần `LIMIT 1001` ở mọi hồ sơ có p95 cạnh 300 ms.
- [ ] R9.5: INSERT một bản ghi và UPDATE một cột slot dưới WITH CHECK của policy, trong soak của harness ở P0 và tổ
      hợp thắng, có p95 cạnh 10 ms; sai nếu lần ghi đi vòng đường ghi mô phỏng của harness.
- [ ] R9.6: giao một bản ghi có p95 cạnh 20 ms, giao dịch gồm dòng outbox và audit; chia sẻ tay đo và ghi cùng bảng cho
      W2; sai nếu giao dịch thiếu một trong hai dòng đó.
- [ ] R9.7: tính sổ tầm cho một chủ thể có p95 cạnh 50 ms, kể cả quản lý có 5.000 cấp dưới, và mảng tính được bằng mảng
      của `profiles_and_scopes` ở mọi cặp (hành động, nhánh) mà nó đặt, cho mọi chủ thể hồ sơ; sai nếu thời gian đo trên mảng gieo sẵn thay vì hàm tính.
- [ ] R9.8: lời gọi cửa trên dòng `valid` có p95 cạnh 1 ms.
- [ ] R9.9: tính lại 5.000 chủ thể sau một lần tăng epoch, bốn kết nối, dưới tải hỗn hợp, có tổng cạnh 120 s và số của
      một kết nối; thu hồi trên hai kết nối không bao giờ để câu lệnh sau commit thấy tầm cũ, kiểm bằng ít nhất 1.000
      lần lặp.
- [ ] Xong: `make bench-record-access SCALE=smoke` xanh.

## Nguồn

- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:31-33`; spec: R9.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:72-87` (khóa chia sẻ, `grants_valid_until`, sổ tầm và cửa);
  spec: R5, R9.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:134-139`; spec: R9 (V4.32: một harness, một seed).
- `db/migrations/sql/0001_platform_baseline.sql:770` (policy tenant chưa ở dạng InitPlan); spec: R9.1.
- `scripts/bench_records_storage.py:1-20` (chỗ dành cho biến thể chính sách, mã thoát);
  `scripts/bench_records_storage/records_bench/ddl.py` (bản thay `studio.principal_scopes` và `studio.acl_*`, policy
  sáu nhánh của A1); `scripts/bench_records_storage/records_bench/seed.py` (cột `read_grants`, `profiles_and_scopes`);
  spec: R9.
- `.claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md` (harness, seed, tải, hồ sơ quyền, mã thoát
  của bước 6); ADR-0107 (Accepted) quyết 2.

## Comments

- 2026-10-23 (agent): cỡ dữ liệu theo D12 (người yêu cầu, 23/10/2026), trả lời DO-14: 10 triệu bản ghi mỗi object,
  50 triệu mỗi tenant, 5.000 người, 200 workspace, cây sâu 6.
- 2026-10-24 (agent): máy đo là máy tham chiếu của YC20 (host chính sau D14), cùng máy của custom-objects/01, thay máy
  2 vCPU, 8 GB của quyết tạm ngày 23/10/2026 (Đạt, 24/10/2026).
- 2026-10-25 (agent): lượt h, theo V4.32 của Đạt: ticket dùng lại harness, seed, tải và hồ sơ quyền của
  custom-objects/01 và chỉ thêm biến thể chính sách, thay cho schema nháp `db/bench/record-access/` với vài cột slot và
  bộ gieo riêng của bước 1 và 2 cũ, nên policy sáu nhánh được đo cùng đủ chỉ mục slot của A1 (bản trả lời phản biện, mục
  4.4 điểm 3 và 4); p95 trên ít nhất 1.000 mẫu nóng và nguội thay cho 20 lần sau một lần làm ấm. Blocked by thêm
  custom-objects/01, cạnh ngoài bảng mục B, đã chạy g.py: không đổi độ sâu của `marketing-pilot/03` (15) hay chuỗi dài
  nhất (18).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness`, chỉ kiểm người dựng (ticket không thêm
  revision Alembic hay route: DDL đo nằm trong harness trên database `dw_bench` riêng), đọc cùng harness của
  custom-objects/01 như nó đứng ở `283fdea` cộng tệp chưa commit của làn 2. `check_plans.py` 24 Đạt. 0 CRITICAL, 10
  HIGH, đã sửa như dưới.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 1: mọi tiêu chí đòi máy tham chiếu và quy mô D12 mà máy đó chưa
  có (Chờ Đạt 23), nên ticket không đóng được, hay số smoke bị chép vào ADR-0105 (Accepted) như số D12. Sửa: ticket này dựng và
  chạy ở `--scale smoke` trên máy dev; lần chạy D12, xét ngưỡng và ghi ADR-0105 (Accepted) tách thành ticket 06
  `ready-for-human`; ticket 03 chờ ticket 06 (Comments của ticket 03). Nếu sai thì: gộp ticket 06 lại làm bước cuối của
  ticket này, và ticket này đứng mở tới khi có máy.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 2: "xanh" không nói một ngưỡng trượt có làm script thoát khác 0
  không. Sửa: bước 7 theo bước 6 của custom-objects/01 (trượt là dòng bảng, thiếu ô là lỗi); thêm tiêu chí cho hai ca.
  Nếu sai thì: thêm cờ `--strict` của harness, và Xong chạy không có cờ đó.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 3: tự kiểm "biến thể chạy trên DDL khác A1 thì đỏ" từ chối chính
  các biến thể đổi `access_key` sang `bigint` mà bước 1 cũ đòi đo. Sửa: mỗi biến thể là A1 cộng phần thay khai báo (bước
  2), tự kiểm so catalog với A1 cộng phần thay đó. Nếu sai thì: trục kiểu khóa đo trên một biến thể A1b của harness do
  custom-objects/01 thêm.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 4: không nói các trục đo theo tích (24 biến thể, mỗi biến thể soak
  2 giờ) hay từng trục, thắng theo tiêu chí nào, hay ở modulus nào. Sửa: bước 2 nêu mốc P0 theo ADR-0105 (Accepted), từng trục quanh
  P0, luật chọn, tổ hợp thắng đo lại, modulus theo luật quyết của custom-objects/01; soak chỉ trên P0 và tổ hợp thắng
  (bước 5). Nếu sai thì: đo theo tích ở trang đầu và tra theo id, soak vẫn chỉ hai biến thể.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 5: R9.7 và R9.9 đo một hàm tính sổ tầm, nhưng seed chỉ có mảng tầm
  tính sẵn bởi `profiles_and_scopes`, `platform.effective_grants` ở head chưa có khóa `obj.*` (tenant-rbac/04), và ticket
  cấm gieo gì ngoài dòng sổ tầm. Sửa: bước 3 cho thêm đầu vào theo hình `platform.effective_grants` dẫn từ tổ chức của
  seed, không thêm bản ghi hay tổ chức, và tự kiểm so mảng tính được với mảng của harness (một sự thật, hai bản, lệch
  thì đỏ: failure-modes #2). Nếu sai thì: bảng đầu vào đó vào `seed(scale)` của custom-objects/01 bằng một lần sửa của
  chủ harness.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 6: kiểm hết hạn mù: seed không đặt `grants_valid_until` và nhánh
  chia sẻ của A1 trong harness không đọc nó (`ddl.py`, `_arms`), nên bỏ điều kiện hết hạn không làm gì đỏ
  (failure-modes #3). Sửa: biến thể chính sách mang điều kiện hết hạn của ADR-0105 (Accepted) quyết 3 (bước 2), mô-đun đặt
  `grants_valid_until` quá khứ trên 1% bản ghi có khóa (bước 3), tự kiểm đọc một bản ghi như vậy (bước 7). Nếu sai thì:
  tự kiểm tạo bản ghi hết hạn trong một giao dịch ROLLBACK thay vì đặt sau seed.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 7: R9.9 "tổng ≤ 120 s" không nói tuần tự hay song song; 5.000 lần
  50 ms tuần tự là 250 s, nên cùng hàm đạt hay trượt tùy cách chạy. Sửa: bốn kết nối, dưới tải hỗn hợp, ghi thêm số một
  kết nối (bước 5). Nếu sai thì: lane `access_closure` của ticket 02 lấy số kết nối mà lần đo cần để đạt.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 8: không nói p95 có gồm gắn setting và lời gọi cửa sổ tầm không,
  trong khi R9 nói "phía máy chủ" và harness đo thời gian giao dịch phía harness. Sửa: bước 5 đo như harness, gồm cửa;
  R9 của spec nói cùng điều. Nếu sai thì: đo thêm `pg_stat_statements` phía máy chủ cho từng câu lệnh và R9 xét số đó.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 9: giao và chia sẻ (R9.6) không nói đi đường nào hay giao dịch gồm
  những câu nào, nên có thể đạt trên đường nhẹ hơn R8.7, R8.8 đòi. Sửa: bản thay SECURITY DEFINER của
  `studio.assign_record`, `studio.share_record` trong giao dịch của đường ghi mô phỏng, có outbox và audit (bước 5).
  Nếu sai thì: ticket 05 đo lại R9.6 qua dịch vụ giao thật.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 10: "chia sẻ tay trên 0,4% và 5% bản ghi (hai lần chạy)" trái với
  seed đang dựng, nơi hai mật độ là một quần thể (0,4% mọi object và 5% `mkt_lead`), nên làm đúng chữ cũ là gieo lần
  hai, trái V4.32. Sửa: bước 3 đo hai mật độ trên hai object của cùng seed. Nếu sai thì: `seed(scale)` của
  custom-objects/01 nhận tham số mật độ do chủ harness thêm.
- 2026-11-03 (agent): MEDIUM, chưa sửa, cho người dựng: (a) A1 của harness đo nhánh chia sẻ không có điều kiện hết hạn và
  sổ tầm một dòng mỗi (hành động, nhánh), khác ADR-0105 (Accepted) quyết 3 và 4, nên số của custom-objects/01 cho A1 là chi phí
  lưu trữ, không phải số của mẫu policy; P0 ở đây là số đó. (b) Phương án thắng khác ADR-0105 (Accepted) quyết 1 hay 4 (ví dụ sổ
  tầm một dòng mỗi hành động) thì ticket 06 sửa quyết định đó qua `mattpocock-skills:domain-modeling` cùng lúc ghi số.
  (c) custom-objects/04 cũng sửa harness (đo lại R9.1 trên mã thật), không có đường phụ thuộc với ticket này; mã nguồn
  của harness không thuộc danh sách tài nguyên va chạm của ticket-template, nhưng hai ticket không dựng song song, và
  ticket sau rebase lên ticket trước. `Makefile` cũng do nhiều ticket sửa: chỉ thêm một target. (d) Dòng tự kiểm dẫn
  mã R9.1 vì ticket không cài kiểm soát nào của mục Kiểm soát; các kiểm soát RLS bản ghi là của ticket 02, 03.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (người dựng mới, đọc cả harness) tìm 9 HIGH,
  đã sửa: (11) seed đặt `mkt_lead` ở `public_read`, nên hàm tính theo R2.2 cho mọi hồ sơ trang lead tầm toàn tenant và
  tự kiểm so mảng luôn đỏ; sửa: hai pha `default_access` (bước 3). (12) nhánh giới hạn dữ liệu không có dữ liệu hay
  setting; sửa: bản thay `studio.actor_boundaries` và danh nghĩa của hồ sơ agent, người ghi `workflow` (bước 2, 3).
  (13) harness thoát 1 khi thiếu một modulus, trái "một modulus"; (14) ô chính sách sẽ chạy cả ô A1 của harness, soak
  gồm; sửa cả hai: lần chạy chính sách chỉ dựng ô chính sách và có luật đủ ô của nó (bước 1). (15) khóa `bigint` cần số
  thứ tự theo tenant không có trong A1; sửa: phần thay của trục gồm cột số đó (bước 2). (16) quyền của 4.990 người ngoài
  hồ sơ và của người đọc T2 chưa nêu; sửa: bước 3. (17) lời gọi cửa chèn vào đâu mà không đổi số của custom-objects/01;
  sửa: câu lệnh tùy chọn sau `scope_sql` chỉ ô chính sách đặt (bước 1). (18) luật chọn phương án thắng chưa nói dòng nào,
  nóng hay nguội, object nào, ngưỡng nào ở smoke; sửa: bước 2. (19) ticket 06 không nói làm gì khi không phương án nào đạt
  ở D12; sửa: tiêu chí R9.1 của ticket 06 đòi câu hỏi mở cho người đặt yêu cầu, `Chặn: ticket 03`. Nếu sai thì: (11)
  hồ sơ hẹp đo trên một object `private` khác thay `mkt_lead`; (12) P0 bỏ nhánh giới hạn và ticket 04 đo nó; (13, 14)
  ô chính sách chạy cả hai modulus như harness; (15) trục `bigint` bỏ khỏi ticket này và ghi là chưa đo; (16) mọi người
  giữ mức Workspace của tôi; (17) cửa gọi trong một vòng khứ hồi riêng; (18) chọn theo nóng, `mkt_lead`; (19) ticket 06
  dựng thêm biến thể tới khi đạt.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận thứ hai, lượt cuối của gate cho phiên bản này (quy tắc
  5 của `checking-plan-readiness`), tìm 8 HIGH, đã sửa, chưa có người đọc mới kiểm lại: (20) không ai có tầm giao hay
  chia sẻ, nên R9.6 đo đường từ chối; sửa: người của hồ sơ Toàn công ty giữ thêm quyền giao và chia sẻ (bước 3). (21)
  hàm theo ADR-0105 (Accepted) quyết 2(c) cho nhánh cấp dưới cả hồ sơ Của tôi có cấp dưới, nên so cả mảng luôn đỏ; sửa:
  so từng cặp (hành động, nhánh) mà harness đặt, phần thừa ghi vào báo cáo (bước 3, 7). (22) agent chạy dưới danh nghĩa
  ai; sửa: người của hồ sơ Toàn công ty, giới hạn `mkt_lead` (bước 2). (23) câu gợi ý cho planner đặt ở policy thì thu
  hẹp tầm; sửa: là bộ lọc "Của tôi" của truy vấn trang ở hai hồ sơ Của tôi (bước 2). (24) trục `bigint` so mảng với gì;
  sửa: đổi khóa của harness qua cùng cột số (bước 7). (25) ô bắt buộc của mỗi phương án chưa nêu; sửa: bước 2. (26) soak
  2 giờ ở smoke trái `scales.SMOKE`; sửa: soak của harness theo scale (bước 5). (27) modulus đọc từ đâu; sửa: `MODULUS`
  của lệnh từ Comments của custom-objects/01 (bước 1, 2); ticket 06 cho mọi dòng R9 trượt cùng lối ra câu hỏi mở. Nếu
  sai thì: (20) một chủ thể riêng giữ quyền giao; (21) hàm tính bỏ nhánh cấp dưới cho hồ sơ không phải quản lý; (22) một
  chủ thể agent riêng như harness; (23) câu gợi ý ở policy chỉ cho nhánh Của tôi; (24) trục `bigint` không so mảng;
  (25) phương án ngoài P0 chỉ đo R9.1, R9.2; (26) soak 2 giờ ở cả hai scale; (27) chạy cả hai modulus.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent. Dựng khi custom-objects/01 `resolved`; không dựng
  song song với custom-objects/04 (cùng sửa harness).
