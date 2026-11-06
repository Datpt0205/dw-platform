# 04 — Rút outbox công bằng theo công ty

Status: resolved (2026-11-06, main)
Blocked by: 03
Area: studio
Yêu cầu: R10.6, G9, RH37

## Mục tiêu

Một lần nhập lớn của một công ty không còn giữ sự kiện outbox của công ty khác lại sau nó. Lane `outbox` hiện có claim
theo công ty, theo vòng xoay, nên sự kiện đến hạn sớm nhất của mỗi công ty được nhận trong ⌈T / K⌉ lần claim, bất kể
công ty khác tồn bao nhiêu sự kiện (spec R10.6, RH37); trong một lần claim, sự kiện của một công ty vẫn giao theo
`occurred_at` (G9). Spike S-RT câu 3 đo claim FIFO hôm nay: sự kiện của công ty D chờ 533,2 giây sau 100.000 sự kiện của
công ty C, còn nguyên mẫu rút theo công ty nhận nó sau 0,086 giây (`db/bench/srt/RESULTS.md:204-219`). Cách làm và các
phương án bị loại ở dòng Quyết định 5/11/2026 của spec. Không thêm tiến trình, lane, bảng hay cột nào; chỉ một index.

## Việc cần làm

Test trước. Test nào viết được trên chữ ký hôm nay thì viết trước trên chữ ký đó và chạy ở commit gốc, ghi kết quả vào
Comments, rồi mới chuyển sang chữ ký mới: G9 qua `claim_batch(limit=3)` phải xanh; test của lane ở bước 2 qua
`build_outbox_consumer` hôm nay (không `tenants_per_tick`) phải đỏ vì khẳng định "handler đã nhận sự kiện của D", không
vì `TypeError`. Các test của bước 1 cần `tenant_limit` và `after_tenant`, chưa có ở commit gốc; chúng thấy đỏ qua các
đột biến của bước 12, chạy ở lần đóng hàng đợi.

1. `packages/python/dw_platform/tests/integration/test_outbox_fair_claim.py`, trên PostgreSQL thật với `dw_app` như
   `test_outbox_drain.py`, chèn hàng loạt bằng `generate_series` qua engine `dw_migrator` (như
   `tests/spike/srt/srtlib/measure.py:1305-1328`) với `occurred_at` và `available_at` đặt rõ (không để `now()` mặc định
   quyết thứ tự), mỗi test một loại sự kiện riêng để không đụng dòng của test khác, `max_attempts` 10, và
   `mark_processed` cho mọi sự kiện vừa nhận trước lần claim kế tiếp, để một test nhiều lần claim không đỏ vì hết lượt:
    - `test_one_company_s_events_are_claimed_oldest_first` (G9): ba sự kiện đến hạn của một công ty, chèn theo thứ tự
      `occurred_at` t3, t1, t2 → một lần claim với `per_tenant_limit` 3 trả t1, t2, t3.
    - `test_a_company_is_not_held_behind_another_company_s_backlog` (RH37): công ty C 5.000 sự kiện đến hạn, mọi
      `available_at` và `occurred_at` sớm hơn sự kiện duy nhất của công ty D → lần claim đầu (`per_tenant_limit` 8,
      `tenant_limit` 8, `after_tenant` None) có sự kiện của D, đúng 8 sự kiện của C, và mọi sự kiện trả về mang
      `tenant_id` của C hay D.
    - `test_companies_beyond_the_per_claim_cap_take_turns` (RH37): bốn `tenant_id` sinh ngẫu nhiên rồi sắp xếp, ba id
      nhỏ là C, E, F mỗi công ty 50 sự kiện, id lớn nhất là D với một sự kiện đến hạn muộn hơn mọi sự kiện của C, E, F;
      `tenant_limit` 2, `per_tenant_limit` 8, lần claim thứ hai nhận `last_tenant` mà lần đầu trả → D có trong một
      trong hai lần claim.
    - `test_the_rotation_wraps_past_the_last_company`: `after_tenant` bằng id lớn nhất trong số công ty có sự kiện đến
      hạn, hai công ty có id nhỏ hơn có sự kiện đến hạn, `tenant_limit` 2 → lần claim nhận cả hai.
    - `test_a_lone_company_is_drained_on_every_claim`: chỉ công ty C có 50 sự kiện đến hạn → ba lần claim liền nhau,
      mỗi lần nhận `last_tenant` của lần trước, mỗi lần trả 8 sự kiện của C.
    - `test_a_company_with_nothing_this_process_can_take_takes_no_turn`: `tenant_limit` 1, D có một sự kiện đến hạn;
      ca (a) công ty C có id nhỏ hơn D và chỉ có sự kiện `available_at` ở tương lai; ca (b) C chỉ có sự kiện đến hạn
      thuộc một loại không có trong `event_types` → ở cả hai ca lần claim đầu trả sự kiện của D.
2. `apps/worker/tests/integration/test_outbox_fairness_db.py` (fixture `migrator`, `app` của
   `apps/worker/tests/integration/conftest.py`), bản thu nhỏ của câu 3: công ty C 5.000 sự kiện, công ty D một sự kiện,
   cùng một loại, với `occurred_at` và `available_at` đặt rõ, mọi giá trị của C sớm hơn của D; `build_outbox_consumer` với `SqlOutboxDrain` thật, `batch_size` 8,
   `tenants_per_tick` 8 và handler ghi lại id → sau lần `consume()` đầu tiên handler đã nhận sự kiện của D đúng một lần.
   Claim FIFO hôm nay cần 625 nhịp cho cùng dữ liệu.
3. `apps/worker/tests/unit/test_outbox_consumer.py`: `FakeDrain` theo đúng hợp đồng mới (chia theo công ty, vòng xoay
   gồm chính `after_tenant`, trả công ty cuối), không chỉ ca test cần; thêm
   `test_the_dispatcher_hands_the_rotation_cursor_to_the_next_claim`: hai lần `consume()` liền nhau → lần claim thứ hai
   nhận đúng `last_tenant` mà lần đầu trả. `apps/worker/tests/unit/test_worker.py` thêm
   `test_outbox_tenants_per_tick_outside_its_range_is_refused`: `outbox_tenants_per_tick` bằng 0 hay 65 →
   `ValidationError` lúc dựng settings.

Migration:

4. Revision Alembic mới bằng `uv run alembic revision -m "outbox claim by company"` trong `db/migrations` (id ngẫu
   nhiên; `down_revision` trỏ vào head lúc commit) tạo index `ix_outbox_events_due_by_tenant` trên
   `platform.outbox_events`: cột `(tenant_id, available_at)`, `INCLUDE (event_type, occurred_at, attempts)`, một phần
   với `WHERE processed_at IS NULL AND dead_at IS NULL`; downgrade `DROP INDEX`. Vị từ một phần phải trùng chữ với điều
   kiện của claim, không thì planner không dùng index. Giữ `ix_outbox_events_claimable`, vì `oldest_pending_at` của
   `backlog()` đọc `min(occurred_at)` qua mọi công ty bằng nó. Bất biến: không bảng, cột, policy hay quyền nào đổi, nên
   `test_rls_coverage.py`, `test_privileges.py` và `test_offboarding_coverage.py` phải xanh mà không sửa; offboarding
   xóa dòng outbox như hôm nay, index đi theo dòng. Index không `CONCURRENTLY` (revision chạy trong giao dịch): bảng hôm
   nay nhỏ, và docstring của revision nói một triển khai có hàng tồn lớn thì lần nâng cấp khóa ghi outbox trong lúc
   dựng index.

Claim:

5. `packages/python/dw_platform/src/dw_platform/domain/outbox.py`: thêm dataclass `OutboxClaim` cạnh
   `OutboxBacklog`, hai trường `events: list[OutboxEvent]` và `last_tenant: UUID | None`.
6. `OutboxDrainPort.claim_batch` (`packages/python/dw_platform/src/dw_platform/application/ports.py:303-316`) nhận
   `event_types`, `per_tenant_limit`, `tenant_limit`, `max_attempts`, `after_tenant: UUID | None` (chỉ từ khóa) và trả
   `OutboxClaim`; docstring nói vòng xoay, cận ⌈T / K⌉ của R10.6 và rằng con trỏ là của người gọi.
7. `SqlOutboxDrain.claim_batch`
   (`packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:50-95`), một giao dịch dưới
   `_ENABLE_DRAIN` như hôm nay:
    - liệt kê các công ty có dòng chưa xử lý, chưa chết bằng quét nhảy (CTE đệ quy lấy `tenant_id` nhỏ nhất lớn hơn id
      vừa tìm, mỗi bước một lần dò index), rồi giữ công ty có ít nhất một dòng đến hạn (`available_at <= now()`,
      `event_type` trong `event_types`) bằng một lần dò `EXISTS` trên index của bước 4, để chi phí không theo hàng tồn
      đến hạn hay số dòng đang lùi thời gian; dòng đến hạn thuộc loại không ai giao vẫn bị đọc qua như claim hôm nay
      (bước 13, ca 3); `tenant_id` là `NOT NULL`
      (`db/migrations/sql/0001_platform_baseline.sql:306`), nên không dòng nào lọt khỏi phép liệt kê;
    - lấy tối đa `tenant_limit` công ty trong số đó theo thứ tự `tenant_id` tăng dần, bắt đầu từ công ty đầu tiên lớn
      hơn `after_tenant`, hết thì quay về id nhỏ nhất, tới và gồm chính `after_tenant`; `after_tenant` None thì từ id
      nhỏ nhất;
    - với mỗi công ty được chọn, tối đa `per_tenant_limit` dòng đến hạn của chính công ty đó thuộc `event_types`, theo
      `available_at` rồi `occurred_at`, `FOR UPDATE SKIP LOCKED` (một `LATERAL`, hay một câu mỗi công ty trong cùng
      giao dịch: chạy cả hai và xem `EXPLAIN`, đừng tin tài liệu);
    - giữ nguyên hai nhánh hiện có trên tập dòng đó: dòng đã hết lượt thì đặt `dead_at` và không trả (R10.2), dòng còn
      lại tăng `attempts`; câu UPDATE nhận danh sách id đã chọn, không viết `IN (SELECT ... SKIP LOCKED)` (RESULTS.md
      Phát hiện 1);
    - trả `OutboxClaim`: sự kiện sắp theo `occurred_at` như hôm nay (G9); `last_tenant` là công ty cuối theo thứ tự
      vòng xoay trong số công ty đã chọn, kể cả công ty mà mọi dòng đã bị khóa hay đã hết lượt; `None` khi không chọn
      công ty nào.
8. `apps/worker/src/dw_worker/consumers/outbox.py`: `build_outbox_consumer` nhận thêm `tenants_per_tick` (chỉ từ
   khóa, cạnh `batch_size`, không có mặc định, để composition root quên truyền là `TypeError` lúc khởi động); `consume()` giữ `after_tenant` trong closure (bắt đầu `None`), truyền vào mỗi lần claim và
   đặt bằng `last_tenant` vừa trả; docstring nói `batch_size` là trần mỗi công ty một nhịp. Con trỏ chỉ sống trong tiến
   trình: khởi động lại thì vòng xoay bắt đầu lại, cận của R10.6 vẫn đúng.
9. `apps/worker/src/dw_worker/settings.py:214-216`: chú thích của `outbox_batch_size` thành trần mỗi công ty một nhịp;
   thêm `outbox_tenants_per_tick: int = Field(default=8, ge=1, le=64)`, giá trị ngoài miền làm worker không khởi động;
   `apps/worker/src/dw_worker/main.py:626-636` truyền nó.
10. Mọi chỗ gọi `claim_batch` theo chữ ký mới, cùng khẳng định như cũ: `test_outbox_drain.py`,
    `test_outbox_dead_letters.py`, và `tests/spike/srt/srtlib/measure.py:1337` (`per_tenant_limit` 100,
    `tenant_limit` 8, con trỏ như bước 8), để harness của câu 3 đo được claim mới.
11. `.claude/plans/studio/runtime-hardening/mutations/03.yaml`: mỗi đột biến của RH27, RH28 có `old` là một dòng của
    `outbox_drain.py` mà bước 7 viết lại thì đổi `old`, `new` theo mã mới, giữ cùng ý (bỏ điều kiện `available_at`, bỏ
    điều kiện `dead_at`, bỏ nhánh hết lượt), vì `scripts/mutate.py` từ chối một đột biến không đổi gì và 03.yaml chưa
    chạy (chạy ở lần đóng hàng đợi).
12. `mutations/04.yaml`, chưa chạy: (a) chọn dòng theo một thứ tự chung, không chia công ty →
    `test_a_company_is_not_held_behind_another_company_s_backlog` đỏ; (b) xếp công ty theo `min(available_at)` thay vì
    vòng xoay → `test_companies_beyond_the_per_claim_cap_take_turns` đỏ; (c) bỏ qua `after_tenant` (mỗi lần bắt đầu từ
    id nhỏ nhất) → cùng test đỏ; (d) consumer luôn truyền `None` →
    `test_the_dispatcher_hands_the_rotation_cursor_to_the_next_claim` đỏ; (e) bỏ điều kiện `available_at`, hay điều
    kiện `event_type`, khỏi phép giữ công ty → `test_a_company_with_nothing_this_process_can_take_takes_no_turn` đỏ;
    (f) bỏ nhánh quay vòng → `test_the_rotation_wraps_past_the_last_company` đỏ; (g) quay vòng dừng trước
    `after_tenant` → `test_a_lone_company_is_drained_on_every_claim` đỏ; (h) bỏ điều kiện công ty ở bước chọn dòng →
    `test_a_company_is_not_held_behind_another_company_s_backlog` đỏ.
13. Ghi vào Comments `EXPLAIN (ANALYZE, BUFFERS)` của câu claim ở ba ca, mỗi ca thêm mười công ty khác có vài sự kiện:
    100.000 dòng đến hạn của C; 100.000 dòng của C mà 30.000 dòng sớm nhất đang lùi thời gian; 100.000 dòng của C thuộc
    một loại không ai giao cộng một sự kiện của D. Ở ca thứ hai, bước chọn dòng của C không đọc 30.000 dòng đang lùi; ở
    ca thứ ba, chi phí đọc qua dòng không ai giao là lỗi có sẵn của claim hôm nay (index `occurred_at` cũng đọc qua
    chúng), ghi số đọc được và không sửa ở đây.

Không thuộc ticket này (hàng Ngoài phạm vi của spec): công bằng giữa các workspace của một công ty, ưu tiên theo loại
hay gói, hàng `knowledge.ingest_jobs`, hàng lượt chạy Studio, và lease chống hai tiến trình worker cùng giao một sự kiện.

Ở lần đóng hàng đợi (`.claude/rules/wave-close.md`, `.claude/rules/latency.md`): chạy `mutations/04.yaml` và
`mutations/03.yaml`; P50, P95, P99 của `claim_batch` ở ba ca của bước 13, trước (commit bắt đầu hàng đợi) và sau, trần
P95 300 ms như một thao tác API; chạy lại `uv run python tests/spike/srt/run_srt.py measure q3` ở 100.000 sự kiện, D phải
được nhận trong 1 giây (533,2 giây hôm nay); số ghi vào Comments.

## Tiêu chí chấp nhận

- [ ] G9: `test_one_company_s_events_are_claimed_oldest_first` viết trước, xanh ở commit gốc và sau thay đổi; đảo
      thứ tự `occurred_at` của lô trả về → đỏ.
- [ ] R10.6 (RH37): C có 5.000 sự kiện đến hạn sớm hơn sự kiện duy nhất của D → lần claim đầu có sự kiện của D, đúng 8
      sự kiện của C và không sự kiện của công ty nào khác; chọn dòng theo một thứ tự chung, hay bỏ điều kiện công ty ở
      bước chọn dòng → đỏ.
- [ ] R10.6 (RH37): `tenant_limit` 2, C, E, F mỗi công ty 50 sự kiện sớm hơn, D có `tenant_id` lớn nhất → D được nhận
      trong 2 lần claim liên tiếp; xếp công ty theo sự kiện đến hạn sớm nhất, hay bỏ qua `after_tenant` → đỏ.
- [ ] R10.6: `after_tenant` bằng id lớn nhất, hai công ty id nhỏ hơn có sự kiện đến hạn, `tenant_limit` 2 → lần claim
      nhận cả hai; bỏ nhánh quay vòng → lần claim trả rỗng, đỏ.
- [ ] R10.6: chỉ một công ty có 50 sự kiện đến hạn → ba lần claim liền nhau, mỗi lần 8 sự kiện của nó; quay vòng dừng
      trước `after_tenant` → lần thứ hai trả rỗng, đỏ.
- [ ] R10.6: `tenant_limit` 1, C có id nhỏ hơn D và chỉ có sự kiện đang lùi thời gian, hay chỉ có sự kiện thuộc loại
      không ai giao → lần claim đầu trả sự kiện của D; bỏ điều kiện `available_at` hay `event_type` khỏi phép giữ công
      ty → C chiếm lượt, lần claim trả rỗng, đỏ.
- [ ] R10.6 (RH37): lane thật trên PostgreSQL thật, C 5.000 sự kiện, D một sự kiện đến hạn muộn hơn → handler nhận sự
      kiện của D đúng một lần ngay ở lần `consume()` đầu; viết trước trên `build_outbox_consumer` hôm nay, test đỏ ở
      commit gốc vì handler chỉ nhận 8 sự kiện của C.
- [ ] R10.6: hai lần `consume()` liền nhau → lần claim thứ hai nhận đúng `last_tenant` lần đầu trả; consumer luôn truyền
      `None` → đỏ. `outbox_tenants_per_tick` bằng 0 hay 65 → settings từ chối; bỏ `ge`, `le` → đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_platform/tests/integration/test_outbox_fair_claim.py packages/python/dw_platform/tests/integration/test_outbox_drain.py packages/python/dw_platform/tests/integration/test_outbox_dead_letters.py packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py apps/worker/tests/unit apps/worker/tests/integration/test_outbox_fairness_db.py` xanh.

## Nguồn

Đọc ở `bc7cd77` (5/11/2026):

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:50-95` (`claim_batch`: một thứ tự
  `occurred_at` chung, đánh dấu chết dòng hết lượt, tăng `attempts`, sắp lại theo `occurred_at`)
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:35` (`app.worker_drain`, mỗi giao
  dịch)
- `packages/python/dw_platform/src/dw_platform/application/ports.py:294-330` (`OutboxDrainPort`)
- `apps/worker/src/dw_worker/consumers/outbox.py:80-115` (`build_outbox_consumer`, một claim mỗi nhịp, giao tuần tự)
- `apps/worker/src/dw_worker/main.py:626-636` (đăng ký lane `outbox`)
- `apps/worker/src/dw_worker/settings.py:55` (`poll_interval_seconds` 1 giây), `apps/worker/src/dw_worker/settings.py:214-220`
  (`outbox_batch_size` 8, `outbox_max_attempts` 3)
- `db/migrations/versions/65443fe9fd9a_run_status_checks_and_outbox_backoff.py:82-95` (`available_at`, `dead_at`,
  `ix_outbox_events_claimable (occurred_at, available_at)`, `ix_outbox_events_dead`)
- `db/migrations/sql/0001_platform_baseline.sql:304-319` (bảng, `tenant_id` `NOT NULL`),
  `db/migrations/sql/0001_platform_baseline.sql:892` (policy `worker_drain_outbox_events`)
- `db/bench/srt/RESULTS.md:204-219` (câu 3: 533,2 giây FIFO, 0,086 giây theo công ty, 0,514 giây ở làn lượt chạy)
- `tests/spike/srt/srtlib/measure.py:1290-1414` (harness câu 3), `tests/spike/srt/srtlib/db.py:215-236` (nguyên mẫu
  `srt.outbox_scopes_due`)
- `infra/compose/docker-compose.prod.yml:37-44` (một worker)
- spec: R10.6, G9, RH37; R10.1, R10.2 (giữ nguyên trên tập dòng mới); foundations-hardening:R2.6 (module được đặt
  `app.worker_drain`, không đổi).

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): ticket viết theo quyết sau spike S-RT mục 3 (studio.md, 4/11/2026) và
  dòng Quyết định 5/11/2026 của spec: claim chia theo công ty trong lane `outbox` hiện có, vòng xoay `tenant_id` với
  con trỏ trong bộ nhớ của mỗi tiến trình, một index một phần mới, không tiến trình, bảng hay cột mới. Nếu sai thì: xem
  dòng Nếu sai thì của dòng Quyết định đó.
- 2026-11-05 (agent): cặp ticket: `.claude/plans/studio/telemetry-and-audit/issues/02-cay-span-va-mot-trace-id.md` thêm
  cột `trace_parent` vào `platform.outbox_events` và đổi dispatcher (`apps/worker/src/dw_worker/consumers/outbox.py`),
  cùng bảng và cùng tệp với ticket này, chưa có đường phụ thuộc; ticket đó phải thêm đường dẫn tới ticket này vào dòng
  Blocked by của nó (spec, Phụ thuộc; OPS-b). record-access/05 chỉ chèn dòng `studio.record.assigned` vào outbox, không
  đổi bảng, claim hay dispatcher: không đụng.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (script 24 Đạt; builder check, boundary
  walk, lượt xác nhận): 0 CRITICAL, 3 HIGH. Đã sửa: (1) quay vòng gồm chính `after_tenant`, thêm
  `test_a_lone_company_is_drained_on_every_claim`, vì không gồm thì một công ty duy nhất có hàng tồn chỉ được rút cách
  một nhịp; (2) test viết trước trên chữ ký hôm nay (G9 xanh, test của lane đỏ vì khẳng định), test cần chữ ký mới đỏ
  qua đột biến, không đỏ vì `TypeError`. Nhận rủi ro (dòng Quyết định 5/11/2026 của spec): (3) cặp với
  telemetry-and-audit/02 chưa có đường phụ thuộc. MEDIUM đã sửa: index `(tenant_id, available_at)` và chọn trong công
  ty theo `available_at`, để dòng đang lùi thời gian không bị quét mỗi lần claim; mỗi sự kiện trả về thuộc công ty
  được chọn, đột biến (h); T của R10.6 chỉ đếm loại tiến trình giao, công ty chỉ có loại không ai giao không chiếm
  lượt; miền 1 tới 64 có test; test của lane đặt `occurred_at`, `available_at` rõ. Nếu sai thì: chọn trong công ty
  theo `occurred_at` (dòng Nếu sai thì của Quyết định).
- 2026-11-05 (agent): gate MEDIUM, chưa sửa, cho người dựng hay đợt sau: (1) cận của R10.6 tính bằng lần claim, không
  bằng giây: một nhịp giao tuần tự tới `outbox_tenants_per_tick × outbox_batch_size` (64) sự kiện, nên handler chậm
  của một công ty kéo dài nhịp của mọi công ty; đo ở lần đóng hàng đợi, trần thời gian mỗi lần giao là quyết định
  riêng. (2) dòng đến hạn thuộc loại không ai giao (như `studio.record.assigned` của record-access/05) tích mãi và bị
  đọc qua mỗi lần claim, như hôm nay (`failure-modes.md` #6); hàng "Xóa dòng outbox đã xử lý" của Ngoài phạm vi không
  phủ chúng. (3) M1, M6, M7 của ticket 03 vẫn chưa có chủ (hủy trong resume ghi `failed`, việc của DW ở `in_progress`
  khi tiếp tục hẹn giờ chết, thư chết không ai xóa hay đóng mà không phát lại, nên `DwOutboxDeadLetters` có thể báo
  mãi). (4) R9.1 không nói lượt resume còn sống mà chạy quá `stale_run_after_seconds` có bị rào trước khi lượt mới của
  thread chạy hay không. (5) phát lại hai lần cùng lúc hay một id không chết: mã của ticket 03 (`SqlDeadLetters.replay`)
  chỉ đổi dòng còn `dead_at`, đặt `available_at = now()` và thoát 2, nhưng R10.4, R10.5 chưa nói điều đó. LOW đã sửa:
  `tenant_id` `NOT NULL` có neo; `max_attempts` 10 và `mark_processed` giữa các lần claim trong test; `tenants_per_tick`
  không có mặc định; tên test settings.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent): dựng xong.
    - Test trước, ở commit gốc (`f4a56a0a`): G9 qua `claim_batch(limit=3)` xanh; RH37 qua chữ ký cũ đỏ vì khẳng định
      (không có sự kiện của D); test của lane qua `build_outbox_consumer` không `tenants_per_tick` đỏ vì khẳng định
      (`assert 0 == 1`: handler chỉ nhận 8 sự kiện của C), không vì `TypeError`.
    - Đã làm: revision `8a693dcd2c04` (`ix_outbox_events_due_by_tenant`, vị từ trùng chữ); `OutboxClaim`;
      `OutboxDrainPort.claim_batch(event_types, per_tenant_limit, tenant_limit, max_attempts, after_tenant)`;
      `SqlOutboxDrain`: CTE đệ quy quét nhảy công ty, `EXISTS` giữ công ty có dòng đến hạn đúng loại, thứ tự vòng
      xoay `coalesce(tenant_id <= after, false), tenant_id`, chọn dòng bằng một `LATERAL ... FOR UPDATE SKIP LOCKED`
      (chạy được trên PG 16, không cần câu mỗi công ty), hai nhánh hết lượt/tăng `attempts` giữ nguyên;
      `build_outbox_consumer(tenants_per_tick=…)` giữ con trỏ trong closure; `outbox_tenants_per_tick` 1-64; mọi
      chỗ gọi theo chữ ký mới (kể cả `test_memory_review_db.py` của worker, không có trong danh sách bước 10).
    - (agent, theo ủy quyền 31/10/2026) thêm `test_a_company_s_backing_off_and_dead_events_stay_out_of_its_claim`:
      đột biến RH27, RH28 của 03.yaml nay nằm ở bước chọn dòng của công ty, mà test cũ không giết được (công ty chỉ có
      dòng đang lùi hay đã chết thì không được chọn ở bước trước); test mới đặt một dòng đến hạn cạnh hai dòng đó.
      Đột biến (a) của bước 12 là (h) dưới hình câu này, ghi ở đầu 04.yaml. Nếu sai thì: tách thêm một đột biến cho
      (a).
    - `EXPLAIN (ANALYZE, BUFFERS)` (DB test của lane 1, mỗi ca thêm mười công ty vài sự kiện, sau `ANALYZE`): ca 1
      (100.000 dòng đến hạn của C) bước công ty 2,3 ms / 380 buffer, bước dòng 0,30 ms / 62 buffer; ca 2 (30.000
      dòng sớm nhất của C đang lùi) bước dòng 0,26 ms / 62 buffer, không đọc 30.000 dòng đang lùi (Index Cond
      `available_at <= now()`), bước công ty 28,5 ms / 3.434 buffer vì `EXISTS` đọc qua 100.000 dòng đến hạn thuộc
      loại khác còn lại từ ca 1; ca 3 (100.000 dòng của C thuộc loại không ai giao, một của D) bước công ty 50,6 ms /
      6.088 buffer, bước dòng 0,37 ms: đọc qua dòng không ai giao là lỗi có sẵn, không sửa ở đây.
    - Test: `test_outbox_fair_claim.py` 8 (Postgres), `test_outbox_drain.py`, `test_outbox_dead_letters.py` theo chữ
      ký mới (19 cùng nhau), `test_outbox_fairness_db.py` 1 và `test_memory_review_db.py` (worker, 12 cùng nhau),
      unit worker 158, unit dw_platform 413; `test_rls_coverage`, `test_privileges`, `test_offboarding_coverage` 163
      xanh không sửa; mypy sạch.
    - `mutations/04.yaml` 10 đột biến, `03.yaml` RH27, RH28 đổi `old` theo mã mới; chưa chạy `mutate.py`; chạy tay (c)
      (bỏ con trỏ), đỏ.
    - Còn ở lúc đóng hàng đợi: `mutate.py` cho 04.yaml và 03.yaml; P50/P95/P99 của `claim_batch` ở ba ca của bước 13
      so với commit bắt đầu hàng đợi; `uv run python tests/spike/srt/run_srt.py measure q3` ở 100.000 sự kiện.
