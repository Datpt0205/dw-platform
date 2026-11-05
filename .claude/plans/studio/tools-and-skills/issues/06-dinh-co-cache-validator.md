# 06 — Đếm lược đồ sống, đo tỉ lệ trúng và định cỡ cache validator của cửa công cụ

Status: ready-for-agent
Blocked by: 03
Area: studio
Yêu cầu: R1.1, R1.2

## Mục tiêu

Mỗi lời gọi công cụ dữ liệu tenant kiểm đầu vào và đầu ra qua `tool_problems` (R1.1, R1.2), và lần kiểm chỉ dưới 1 ms
p95 khi validator của lược đồ còn trong LRU của cửa, `_cached_tool` với `maxsize=256`, một bản cho mọi công ty của tiến
trình; một lần trượt dựng lại validator, 16-23 ms p95, gần hết là `check_schema` (discovery/16 `## Answer`; Open 6 của
ADR-0116 (Accepted)). Chưa ai đếm một worker giữ bao nhiêu lược đồ sống. Ticket này đếm chúng trên dữ liệu dáng chăm
sóc lead và ở một tập công ty cỡ D12, đưa tỉ lệ trúng ra metric OpenTelemetry như nền tảng đã phát, rồi định cỡ cache
theo số đã đếm, với P50/P95/P99 của một lời gọi công cụ đo trước và sau so với ngân sách 300 ms của
`.claude/rules/latency.md`.

Khóa của cache đã kiểm (5/11/2026, `7a0c110c`), không phải phát hiện bảo mật: khóa là toàn bộ JSON chuẩn của lược đồ
(khóa sắp xếp), và validator dựng từ chính chuỗi khóa đó, với format checker là hằng của mô-đun và một `Registry()`
rỗng dựng mới ở mỗi lần trượt, nên giá trị của một khóa là hàm của riêng nội dung khóa. Hai công ty chỉ dùng chung một
mục khi lược đồ của họ giống nhau từng byte, và mục đó cho cả hai đúng một hành vi; không có khóa theo tên công cụ. Bước
4 giữ tính chất này khi cache đổi, và ghi quyết định mà câu "Cache keys and object paths include tenant/workspace" của
`CLAUDE.md` (Tenancy and authorization) đòi, vì khóa không có công ty.

## Việc cần làm

1. **Đếm, bằng cách chạy.** Script `scripts/bench_tool_schema_cache.py` (cạnh `scripts/bench_json_schema.py`, không vào
   `testpaths`), trên PostgreSQL thật như `apps/api/tests/integration` (`latency.md` bước 2), hạt giống cố định:
    - Dáng chăm sóc lead (agent, tạm: repo chưa định nghĩa trường của các đối tượng thí điểm): một công ty với ba đối
      tượng, lead mang 30 trường của `thirty_property_schema` trong `scripts/bench_json_schema.py` (dáng lead của
      discovery/16), chiến dịch và tương tác mỗi đối tượng 10 trường trải các họ slot của custom-objects/04; một Bộ công
      cụ ghim `obj_<api_name>__search` và `obj_<api_name>__get` cho cả ba (ticket 03); và một `BindingDecl` VARIABLE cho
      mỗi biến của `configs/packs/marketing/workflows/lead_care@1.0.0.yaml` (`sender_address`, `sales_assignee_id`,
      `reply_wait_seconds`, `min_confidence`), cùng lược đồ. Lead có hai `schema_version` sống (một lượt ghim v3 còn dở
      khi v4 phát hành, như tiêu chí R6.1 của ticket 03). Nếu sai thì: khi gói thí điểm có định nghĩa đối tượng thật,
      chạy lại script trên đó.
    - Tập công ty cỡ D12 (agent, tạm: D12 nói cỡ mỗi công ty, không nói số đối tượng hay số công ty mỗi tiến trình): 1,
      10, 50 và 100 công ty dáng trên, cộng một "công ty lớn" 20 đối tượng × 2 `schema_version` sống nằm trong cả bốn
      tập. Mỗi công ty tổng hợp có lược đồ khác từng byte với công ty khác: theo hạt giống, lead thêm một tới ba trường
      tùy biến riêng và chiến dịch một picklist với giá trị riêng; ghi thêm ca cận dưới, mọi công ty là bản sao y nguyên.
      Nếu sai thì: chạy lại script với số thật khi số công ty mỗi tiến trình được chốt; số là tham số dòng lệnh, không
      sửa mã.
    - Trong tiến trình của script, dựng lại cửa với `maxsize=None` (`functools.lru_cache(maxsize=None)` quanh
      `_cached_tool.__wrapped__`); với mỗi công ty dựng Bộ công cụ qua `ToolAssembler.build` (nơi `check_profile` cũng
      tra cache), cho một lượt qua đường kiểm binding của lượt (`_invalid_names` trong
      `packages/python/dw_studio/src/dw_studio/core/application/bindings.py`, gọi `variable_problems`), và gọi mỗi công cụ
      một lần qua `ToolExecutor` với vector hợp lệ; rồi đọc `cache_info().currsize`. Ca "cần duyệt" dùng thêm một công cụ
      `connector_action` thử với `approval_policy: always`, gọi qua wrapper LangChain thật trong một graph, chỉ để đếm số
      lần tra, không tính vào số mục.
    - Ghi: số mục mỗi công ty chạy riêng; số mục của cả tập (lược đồ giống nhau giữa công ty gộp một mục); số lần tra mỗi
      lời gọi, là hiệu `hits + misses` trước và sau, cho công cụ không cần duyệt (một lượt gọi) và cần duyệt (từ lời gọi
      tới khi chạy xong sau duyệt, gồm lần node chạy lại khi tiếp tục). Script ghi tập sống của 100 công ty ra một tệp
      JSON cho bước 3.
    - Script bọc `_cached_tool` để ghi, ở mọi lần tra (trúng hay trượt), khóa và nơi gọi: khung stack đầu tiên nằm ngoài
      `json_schema.py` và `tool_schema.py`. Nơi gọi đã biết: `executor.py` (kiểm đầu vào, đầu ra), `langchain_tools.py`
      (wrapper trước khi dừng chờ duyệt), `tool_kinds.py` (`check_profile` của `ToolAssembler.build`) và `bindings.py`
      (`variable_problems`, `declaration_problems`). Khóa nào có nơi gọi ngoài danh sách đó thì script báo; không xếp loại
      theo tập con thuộc tính (v3 và v4 của lead, hay hai công ty, cũng là tập con của nhau). Nếu nơi gọi đó kiểm theo
      lược đồ model thấy đã thu hẹp theo bảo mật trường (một đường mà discovery/16 nói không có), đường đó đổi sang
      `evolve(schema=…)` từ validator đầy đủ của cửa (0,05-0,06 ms p95, discovery/16), một hàm thêm vào `json_schema.py`,
      không qua `_cached_tool` và không cache mới; nơi gọi lạ khác thì ghi ở Comments và mở ticket.
2. **Metric.** Thêm vào `packages/python/dw_observability/src/dw_observability/metrics.py` và `ALL_METRICS`:
   `DW_JSON_SCHEMA_CACHE_LOOKUPS_TOTAL = "dw_json_schema_cache_lookups_total"` (nhãn `cache` ∈ {`tool`, `payload`},
   `result` ∈ {`hit`, `miss`}) và `DW_JSON_SCHEMA_CACHE_ENTRIES = "dw_json_schema_cache_entries"` (nhãn `cache`). Không
   nhãn công ty: cache là của tiến trình, và id công ty là nhãn cardinality cao (`metrics.py:3`). Số đọc lúc scrape từ
   `cache_info()` của hai LRU (`_cached_tool` là `tool`, `_cached` là `payload`), qua một hàm `cache_stats()` mới trong
   `json_schema.py`; không đếm gì trên đường nóng, vì `lru_cache` đã giữ số trúng và trượt. Thêm
   `observe_counter(name, read)` và `observe_gauge(name, read)` vào `TelemetryPort`, `read` là
   `Callable[[], Iterable[tuple[int | float, Mapping[str, object]]]]`, cài ở cả ba bản: `OtelTelemetry` bằng
   `create_observable_counter` và `create_observable_gauge` của meter, `NullTelemetry` không làm gì, `RecordingTelemetry`
   giữ hàm đọc để test gọi; thêm hai tên vào `EMITTERS` của `test_metrics_emitted.py`. Một hàm đăng ký,
   `observe_schema_caches(telemetry)` trong `dw_agent_runtime.tool_schema` (gói phụ thuộc cả `dw_platform` lẫn
   `dw_observability`), mà mỗi root gọi đúng một lần ngay sau chỗ dựng telemetry, ở API và ở worker. `cache_stats()` đọc
   tên mô-đun hiện hành mỗi lần scrape, không giữ tham chiếu lúc đăng ký; ngoài test không ai gọi `cache_clear()`, nên bộ
   đếm đơn điệu trong một tiến trình. Không dùng lane đọc định kỳ: API không có lane, và lời gọi công cụ chạy ở cả hai
   tiến trình.
3. **Định cỡ `_cached_tool`**, theo số của bước 1 và luật sau (agent, tạm):
    - Đo bộ nhớ trong `python:3.12-slim-bookworm` như discovery/16, trên tệp tập sống của bước 1: `tracemalloc` và RSS
      trước, sau khi dựng mọi validator của tập (đầu vào và đầu ra, kể cả đầu ra `{next_cursor, items}` của công ty lớn),
      ghi trung bình và lớn nhất mỗi mục.
    - `maxsize` = max(256, N), N là số mục của tập 100 công ty lược đồ khác từng byte (có công ty lớn) × 2, làm tròn lên
      lũy thừa của 2; khi N × bộ nhớ trung bình mỗi mục vượt 50 MiB (khoảng 5% giới hạn 1 GiB của api và worker ở
      `infra/compose/docker-compose.prod.yml`), lấy lũy thừa của 2 lớn nhất còn vừa 50 MiB, không dưới 256, ghi ở Comments
      số mục còn trượt và giá của chúng, và mở ticket riêng cho cách làm lần trượt rẻ đi; ticket này không bỏ
      `check_schema` ở lần trượt. Cỡ là hằng trong mã, chú thích nêu số đo và ngày, không biến môi trường hay cấu hình
      (failure-modes #1).
    - `_cached` không định cỡ ở đây: lượt của script không chạy workflow nên không đếm được nó; metric của bước 2 cho
      biết nó ở uat. Nếu sai thì: một ticket riêng đếm `_cached` bằng lượt `lead_care` mỗi công ty.
    - Hàng xóm ồn, ở cỡ đã chọn: một công ty xoay vòng qua nhiều lược đồ hơn cỡ cache, trong khi công ty kia gọi Bộ công
      cụ của mình; ghi P95 lời gọi của công ty kia (đo như bước 5). LRU đã đẩy ra theo lần dùng gần nhất, nên không thêm
      khóa theo (công ty, mã băm) hay hạn mức mỗi công ty; nếu P95 đó trượt 300 ms, ghi ở Comments và mở ticket.
4. **Khóa.** Cache đổi cỡ vẫn giữ khóa là toàn bộ JSON chuẩn của lược đồ (hay SHA-256 của nó) và validator dựng từ chính
   nội dung đó. Test mới `packages/python/dw_platform/tests/unit/test_json_schema_cache.py`: hai lược đồ cùng tên công cụ
   `obj_lead__search`, chỉ khác một giá trị `enum`, cho hai validator, mỗi cái nhận vector của mình và từ chối vector của
   kia, theo cả hai thứ tự gọi. Viết `mutations/06.yaml` một đột biến: `tool_validator_for` tra cache theo tập tên thuộc
   tính của lược đồ (bỏ mọi từ khóa khác), giữ validator dựng lần đầu, và test này phải đỏ.

    Hai LRU không có công ty trong khóa, mà `CLAUDE.md` (Tenancy and authorization) nói khóa cache có tenant. Quyết định
    (agent, tạm theo ủy quyền 31/10/2026): giữ khóa theo nội dung, vì giá trị của mục chỉ dựng từ chính nội dung khóa nên
    không mang dữ liệu nào của công ty khác, còn khóa (công ty, mã băm) phải truyền công ty qua
    `ToolBehaviour.validate_input`, `check_profile` và biến binding mà không thêm cách ly nào. Ticket ghi quyết định đó,
    không đổi gì khác: một câu ngay dưới dòng đó của `CLAUDE.md` (một cache mà giá trị chỉ dựng từ toàn bộ nội dung khóa,
    JSON chuẩn hay SHA-256 của nó, được không có tenant trong khóa; ví dụ hai LRU của `json_schema.py`) và một dòng
    Amendments của ADR-0116 (Accepted). Nếu sai thì: khóa (công ty, SHA-256 của JSON chuẩn) như `TenantValidatorCache` của
    `scripts/bench_json_schema.py`, công ty từ ngữ cảnh lượt của executor, của bộ dựng và của binding, và bước 1 đếm lại
    với mục nhân theo số công ty dùng chung lược đồ.

5. **Trễ** (`latency.md`): P50/P95/P99 của một lời gọi `obj_lead__search` qua `ToolExecutor` trên PostgreSQL thật, ≥ 200
   lời gọi mỗi ca, xoay vòng công ty của tập 100 công ty để cache thấy cả tập sống; ca trước (`maxsize=256`) và sau (cỡ
   mới) chạy cùng script, cùng máy, cùng phiên; cộng ca "chỉ trúng" và "chỉ trượt" để tách phần của cache. Phép đo này là
   sản phẩm của ticket, không phải phép kiểm hồi quy: cỡ ở bước 3 chốt theo nó, nên nó chạy trong ticket (câu "Ask" của
   `.claude/rules/wave-close.md`); lượt đo trễ lúc đóng hàng của `latency.md` vẫn đo các thao tác ticket chạm như mọi
   ticket.
6. Ghi số đã đo và cỡ đã chọn vào Open 6 của ADR-0116 (Accepted), thay câu "How many live schemas a worker holds against
   the LRU's 256 is not measured", và vào Comments.

Không dựng song song với ticket nào khác sửa `json_schema.py` hay `telemetry.py` của `dw_observability`.

## Tiêu chí chấp nhận

- [ ] R1.1: Comments có bảng số mục của LRU cửa cho 1, 10, 50, 100 công ty (lược đồ khác từng byte và ca cận dưới), số
      mục mỗi công ty chạy riêng, số lần tra mỗi lời gọi (không duyệt và có duyệt) và danh sách nơi gọi theo khóa; chạy lại
      script cùng hạt giống cho cùng số; một khóa có nơi gọi kiểm lược đồ đã thu hẹp thì đã đổi sang `evolve`, hay
      Comments ghi không có khóa nào ngoài các nơi gọi đã biết của bước 1.
- [ ] R1.1: với `OtelTelemetry` trên `InMemoryMetricReader`, hai lần `tool_problems` trên một lược đồ mới làm
      `dw_json_schema_cache_lookups_total{cache="tool"}` tăng một `miss` và một `hit`, `dw_json_schema_cache_entries`
      tăng 1, và khóa nhãn của mọi điểm đúng là {`cache`, `result`} hay {`cache`}, không nhãn nào khác; một test mỗi root
      thay `observe_schema_caches` trong mô-đun của root bằng một spy và khẳng định nó được gọi đúng một lần với telemetry
      root dựng (không đọc provider toàn cục), đỏ khi gỡ dòng gọi; một lần scrape thật `/metrics` của API và cổng metrics
      của worker sau một lời gọi công cụ, dán vào Comments, có cả hai metric.
- [ ] R1.2: `maxsize` theo luật bước 3, không dưới 256, với bộ nhớ trung bình và lớn nhất mỗi mục, tổng bộ nhớ của cỡ đã
      chọn và P95 của ca hàng xóm ồn ở Comments; cỡ bị chặn ở 50 MiB hay P95 hàng xóm ồn trên 300 ms thì có ticket riêng
      đã mở.
- [ ] R1.1: `test_json_schema_cache.py` xanh, và đột biến của `mutations/06.yaml` làm nó đỏ; câu của `CLAUDE.md` và dòng
      Amendments của ADR-0116 (Accepted) ở bước 4 có trong commit của ticket.
- [ ] R1.2: P50/P95/P99 trước và sau của bước 5 ở Comments; P95 sau ≤ 300 ms và P99 ≤ 1 s, hay trượt thì ghi rõ số; P95
      sau tệ hơn trước 20% thì có lý do hay sửa; số và cỡ ở Open 6 của ADR-0116 (Accepted).
- [ ] Xong: `uv run python -m pytest packages/python/dw_platform/tests/unit/test_json_schema_cache.py packages/python/dw_observability/tests/unit packages/python/dw_agent_runtime/tests/unit/test_tool_schema.py` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/json_schema.py:44` (`_cached`, `maxsize=256`);
  `packages/python/dw_platform/src/dw_platform/application/json_schema.py:128` (`_cached_tool`, `maxsize=256`);
  `packages/python/dw_platform/src/dw_platform/application/json_schema.py:132` (validator dựng từ chuỗi khóa);
  `packages/python/dw_platform/src/dw_platform/application/json_schema.py:137` (`Registry()` rỗng mỗi lần trượt);
  `packages/python/dw_platform/src/dw_platform/application/json_schema.py:142` (khóa là `canonical_json` của lược đồ).
- Tra cache: `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:613` (đầu vào),
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:963` (đầu ra),
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:600` (đầu vào ở wrapper, trước khi
  dừng chờ duyệt), `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_kinds.py:166` (`check_profile` lúc dựng),
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_schema.py:109` (`_checked`, chung cho ba lần kiểm của
  executor và wrapper); `packages/python/dw_studio/src/dw_studio/core/application/bindings.py:113` (`variable_problems`),
  `packages/python/dw_studio/src/dw_studio/core/application/bindings.py:130` (`declaration_problems`).
- Metric: `packages/python/dw_observability/src/dw_observability/telemetry.py:32` (`TelemetryPort`);
  `packages/python/dw_observability/src/dw_observability/metrics.py:3` (nhãn cardinality thấp);
  `packages/python/dw_observability/tests/unit/test_metrics_emitted.py:22` (`EMITTERS`);
  `apps/api/src/dw_api/bootstrap/wiring.py:239` và `apps/worker/src/dw_worker/main.py:248` (dựng telemetry ở hai root).
- Giới hạn bộ nhớ: `infra/compose/docker-compose.prod.yml:47` (worker 1 GiB).
- `.claude/plans/studio/discovery/issues/16-cel-and-jsonschema.md` (`## Answer`, Phát hiện); `scripts/bench_json_schema.py`
  (`thirty_property_schema`, `TenantValidatorCache`, cách đo); quyết 3 và Open 6 của ADR-0116 (Accepted); spec: R1.1,
  R1.2; ticket 03 (R6.1).

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): tách từ phát hiện của discovery/16. Khóa của cache đã kiểm, không phải
  phát hiện bảo mật (Mục tiêu). Ghi lại, mức LOW, không sửa ở đây: thời gian trúng và trượt (0,7 so với 16-23 ms) cho một
  công ty biết lược đồ giống từng byte với lược đồ nó đoán có đang nóng trong tiến trình không, tức có công ty nào khác
  dùng đúng lược đồ đó; nội dung đoán là của chính người đoán, nên kênh này chỉ trả lời có hay không.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate (builder check; không migration, không route nên không đi biên, theo
  `wave-close.md`). Sửa ba HIGH theo khuyến nghị: (B1) công ty tổng hợp có lược đồ khác từng byte, ca bản sao y nguyên
  chỉ là cận dưới, không thì 100 công ty gộp về vài chục mục và cỡ theo một tập sống không có thật; (B2) `maxsize` không
  bao giờ dưới 256; (B3) khóa thu hẹp nhận theo nơi gọi, không theo tập con thuộc tính, vì v3 và v4 của lead cũng là tập
  con của nhau. MEDIUM, sửa luôn: ca cần duyệt dùng một công cụ thử qua wrapper thật; biến binding đếm qua `_invalid_names`;
  bộ nhớ đo trên chính tập sống; test của root bằng spy, không qua provider toàn cục; đo trễ trong ticket kèm lý do; không
  nhãn công ty có tiêu chí. Câu `CLAUDE.md` "Cache keys … include tenant/workspace" mà khóa không đáp: không lộ dữ liệu
  (giá trị là hàm của nội dung khóa), nên giữ khóa và ghi quyết định ở bước 4. Nếu sai thì: bước 4, Nếu sai thì.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) sửa thêm: (B1, HIGH) nơi gọi là khung
  đầu tiên ngoài `json_schema.py` và `tool_schema.py`, ghi ở mọi lần tra chứ không chỉ lần trượt, vì ba lần kiểm của
  executor và wrapper cùng qua `_checked` và lần trượt đầu luôn là `check_profile`; danh sách nơi gọi đã biết có
  `declaration_problems`; (MEDIUM) tập 100 công ty gồm công ty lớn và lấy ca khác từng byte; trần 50 MiB là của
  `_cached_tool`, tính bằng trung bình mỗi mục, đo trong ảnh Linux; trường của ba đối tượng thí điểm lấy tạm từ lead 30
  trường của discovery/16; biến binding là bốn biến của `lead_care`; `_cached` chỉ có metric, không định cỡ ở đây; số lần
  tra của ca cần duyệt gồm lần chạy lại sau duyệt; câu `Registry()` sửa (rỗng, dựng mỗi lần trượt, không phải hằng).
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
