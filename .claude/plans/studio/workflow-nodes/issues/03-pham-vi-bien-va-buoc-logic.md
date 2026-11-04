# 03 — Phạm vi biến, kiểm kiểu khi gửi kiểm định và các bước logic

Status: ready-for-agent
Blocked by: 02, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/usage-and-limits/issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md
Area: studio
Yêu cầu: R1.5, R2.3, R2.4, R3.2, R3.3, R3.5, R4.4, WN5, WN11

## Mục tiêu

Mỗi Biểu thức kiểm kiểu tại vị trí bước, chỉ tham chiếu bước trội, và từ chối Trường không đọc được; người dựng kiểm và
tính thử Biểu thức chỉ ở máy chủ; ba bước logic lát cần với mặc định đóng (workflow-nodes R2.3, R2.4, R3.2, R3.3, R3.5,
R4.4, WN5, WN11).

## Việc cần làm

1. **Môi trường biểu thức theo vị trí**, một hàm `expression_env(...)` ở `dw_studio.workflows` mà bộ kiểm, `draft/scope`
   và hai route `/expressions/*` cùng gọi:
    - `trigger.input`: kiểu từ lược đồ đầu vào mà trình kích hoạt của tài liệu khai, ánh xạ bằng bảng ánh xạ kiểu của
      bước 3 (đường `trigger.input.<trường>`, như WN13 của spec viết). Tài liệu có nhiều mục `triggers[]` khác lược đồ
      thì `trigger.input` chỉ mang các trường mà mọi mục cùng khai với cùng kiểu. Ticket này không dựng phép ánh xạ
      payload bằng CEL ở ingress: workflow-triggers kiểm payload theo lược đồ lúc nhận (dòng Quyết định 4/11/2026 của
      spec).
    - `steps.<id>`: chỉ các Bước trội vị trí đó, theo `dominators()` của `dw_agent_runtime/wflite/ir.py`, không bản sao.
      Kiểu là `step_output_schema(spec, config, on_error)` của ticket 02, trừ loại có kiểu đầu ra theo phụ thuộc (bước 4,
      mục cuối).
    - `run`: `id`, `mode`, `started_at`, `workflow`. Không `now()`.
    - Không có `bindings`, `item` hay `index` ở ticket này: `bindings` vào cùng khóa `bindings[]` của
      workflow-engine/05, `item` và `index` cùng `logic.map` ở W2 (failure-modes #1).
    - Bước không trội không có trong môi trường. Tham chiếu tới nó, có `has()` hay không, là `undeclared_reference` hay
      `undefined_field` của `ExpressionEngine.check` (ticket 01) mà `name` là id một Bước có trong tài liệu, và bộ kiểm
      trả `wf.ref_not_dominating` có con trỏ. `has()` chỉ bảo vệ trường tùy chọn của một Bước trội (như `error`), vì
      binding không lộ AST nên không phân biệt được tham chiếu có `has()` với tham chiếu trần (ADR-0112 (Accepted),
      Amendments 2026-11-04).
    - Mọi lỗi biên dịch khác (`syntax`, `no_matching_overload`, `too_deep`, `source_too_large`, `other`, và
      `undeclared_reference` hay `undefined_field` không mang id Bước) trả mã mới `wf.expression_invalid`, có `kind`
      của lỗi trong chữ lỗi.
2. **Chủ thể của `visible_fields`** (R4.4, WN5; field-security:R4.3; ADR-0114 (Accepted) quyết 4).
    - Trường nào bị lọc: một giá trị kiểu bản ghi trong môi trường mang id đối tượng của nó, và `visible_fields` của
      field-security cho chủ thể và đối tượng đó bỏ các Trường bị ẩn khỏi kiểu `object{...}`. Ticket 04 là loại đầu tiên
      công bố đầu ra kiểu bản ghi; test của ticket này dùng một loại fixture có đầu ra bản ghi `lead` mang `phone`.
    - Lúc gửi kiểm định: chủ thể chạy là người gửi kiểm định, vì chưa tài liệu nào khai điểm gắn run-as; ticket thêm
      điểm gắn đó vào tài liệu (workflow-triggers/01) chuyển phép kiểm này sang giá trị đã duyệt của điểm gắn khi tài
      liệu khai nó. Ở `draft/scope`: người gọi. Trường bị ẩn không có trong cây biến; tham chiếu tới nó →
      `field_not_readable`.
    - Lúc chạy, chỗ chặn thật: chủ thể chạy của lượt. Mọi lần tính Biểu thức của Studio lúc chạy, kể cả mẫu của ticket
      02, đi qua một hàm của ticket này: `check` lại nguồn trong môi trường dựng theo `visible_fields` của chủ thể chạy
      (cache theo khóa của ticket 01), rồi mới `evaluate`. Một `undefined_field` mang tên một Trường bị ẩn →
      `field_hidden` theo Khi lỗi của Bước. Activation không mang Trường bị ẩn. Không bao giờ tính như `null`, vì trường
      wrapper vắng đọc ra `null` (ticket 01 bước 3; failure-modes #5, #7).
3. **Bộ kiểm khi gửi kiểm định**: `validate` của lõi `dw_agent_runtime/wflite/validate.py` nhận `ExpressionEngine`
   (Protocol của `dw_kernel.expressions`) qua tham số; mã vào `MESSAGES`, không có bảng riêng.
    - Trường cấu hình nào là Biểu thức do từ khóa `x-dw-cel` trong schema cấu hình của loại khai, kèm tập kiểu kết quả
      được nhận (`["bool"]` cho một điều kiện, mà ticket 07 dùng cho "Lặp lại khi"). Trường mẫu là `x-dw-sink` của
      ticket 02; ticket này gắn `check_template` vào bộ kiểm.
    - Tham chiếu không trội → `wf.ref_not_dominating`; lỗi biên dịch khác → `wf.expression_invalid` (bước 1). Kết quả
      không thuộc tập kiểu khai, kể cả `dyn` → `wf.type_mismatch` (workflow-engine:R2.6). Lý do cho `dyn`:
      ADR-0114 (Accepted) quyết 4 từ chối json trong điều kiện khi không có `type()` bảo vệ, mà không có AST để thấy `type()`;
      người dựng viết `string(x)`. Trường không đọc được → `field_not_readable` (bước 2), kiểm ở `dw_studio` qua seam
      `STUDIO_RULES` của workflow-engine/01 trên cùng `WorkflowIR`. Hai mã mới vào `MESSAGES` có nhãn vi và en.
    - Bảng ánh xạ kiểu dùng chung, keyed theo kiểu trường của custom-objects, sang đại số kiểu của ticket 01.
    - Đường gói (`PACK_RULES`) không truyền `ExpressionEngine` và giữ tham chiếu nguyên giá trị của wf-lite R3.7.
    - `PathRules` của workflow-engine/01 thêm tập `refused_types`, rỗng ở ticket này, mà bộ kiểm đọc: Bước có loại
      trong tập → `wf.unknown_type`. Ticket 05 và 06, mỗi ticket thêm một dòng vào tập của `STUDIO_RULES` cho loại
      `@1` của wf-lite mà nó thay, nên phần chung nằm ở ticket sớm nhất (ticket 05 và 06 đều chờ ticket này).
4. **Sổ loại của Studio và ba loại bước** (ticket 02 bước 1).
    - Thêm `studio_node_types(ports)` ở `packages/python/dw_studio/src/dw_studio/workflows/node_registry.py` và tham số
      `extra` của `build_node_registry`. Composition root của API và worker truyền `extra=studio_node_types(ports)`
      (workflow-engine/01 bước 6); trùng `type@major` → `ValueError`.
    - Thêm vào `NodeTypeSpec` trường bắt buộc, không mặc định, `allowed_on_error` (tập Khi lỗi loại cho phép), cùng nơi
      đọc là bộ kiểm lõi: `on_error` ngoài tập → `wf.config_invalid` có con trỏ tới `on_error`. Ticket này là nơi đầu
      tiên giới hạn nó (ticket 02 bước 4), và khai giá trị cho mọi mục có lúc đó: sáu loại wf-lite nhận `fail`,
      `continue`, `route` (đường gói từ chối `on_error`, nên giá trị không đổi gì ở đó); `human.approval@2` của ticket 06
      nhận `fail`, `route` (R9.17). `incident` vào tập của
      các loại cho phép nó cùng workflow-engine/07, nơi giá trị đó vào mô hình tài liệu. Bảng `READERS` của ticket 02
      thêm dòng của nó.
    - `data.transform@1` (mới): cấu hình `{fields: {<khóa>: <Biểu thức>}}`, khóa khớp `^[a-z][a-z0-9_]{0,39}$`, 1-50
      khóa (`maxProperties: 50`; 51 khóa → `wf.config_invalid`), mỗi giá trị là `x-dw-cel` mọi kiểu. Đầu ra là đối tượng
      một thuộc tính mỗi khóa, kiểu là `result_type` của Biểu thức đó. Không ghi `variables[]`. `block` `none`,
      `ends_run` và `exits_loop` sai, `dependencies` `()`, Khi lỗi `fail`, `continue`, `route`.
    - `logic.switch@1` (wf-lite, sửa tại chỗ): giữ `on`, `cases`, `default` và đầu ra `{case}`. Trên đường Studio, `on`
      là đúng một `{{ expr }}` (`x-dw-sink` `json`) có kiểu kết quả `string`, `int` hay `bool` (`x-dw-cel`), khác thì
      `wf.type_mismatch`. Một nhánh khớp khi `scalar_text` của giá trị (ticket 02) bằng khóa của nhánh; không nhánh nào
      khớp thì làn `default`. `on` ra `null` hay lỗi lúc chạy → Bước lỗi `expression_error` theo Khi lỗi, không bao giờ
      đi làn `default` (failure-modes #7). Mỗi làn là một làn Bước; cạnh có điều kiện do phép hạ của workflow-engine/01
      dựng (V4.24). Khi lỗi `fail`, `route`. `block` `choice` như workflow-engine/01 đã khai. Mọi gói trong
      `configs/packs` vẫn nạp và giữ nghĩa (ticket 02 bước 1).
    - `flow.stop@1` (mới): cấu hình rỗng (`additionalProperties: false`), không đầu ra. Lượt kết thúc `completed`, và
      `outcomes[]` được tính như mọi lượt kết thúc (workflow-engine:R1.9). `ends_run` đúng, `exits_loop` sai, `block`
      `none`, `dependencies` `()`, Khi lỗi chỉ `fail`.
    - `opens_wait`: hai loại mới khai sai nếu trường đã có lúc ticket này dựng (workflow-engine/06 thêm nó).
    - Kiểu đầu ra theo phụ thuộc: một loại mà đầu ra lấy từ thành phần nó trỏ tới (`flow.subworkflow@1` của ticket 08)
      nhận kiểu từ phiên bản mà phụ thuộc phân giải. Lúc gửi kiểm định là phiên bản niêm phong ghim; ở lưu nháp và
      `draft/scope` là phiên bản `live` của thành phần đó lúc gọi. Hàm môi trường của bước 1 nhận một ánh xạ
      `node_id → schema đầu ra` từ seam Studio; danh mục của ticket 02 nêu đầu ra của loại đó là `dyn`.
5. **Mặc định đóng**: trên đường gói, một bước không khai Khi lỗi chạy như `fail`; trên đường Studio, `STUDIO_RULES` bắt
   buộc `on_error`, thiếu thì `wf.schema_invalid`, không bao giờ điền `continue`. Một `logic.switch` thiếu Nhánh ra mặc
   định → `wf.router_not_total`, không niêm phong.
6. **Ba route** (dạng sub-resource của ADR-0108 (Accepted); mã lỗi theo mục API của spec):
    - `GET /api/v1/studio/workflows/{id}/draft/scope?node=`, `POST /api/v1/studio/expressions/check`,
      `POST /api/v1/studio/expressions/evaluate`. Cả ba cần `studio.workflows.edit` trên quy trình (thiếu → 403). Quy
      trình của công ty khác hay id không có → 404 giống hệt nhau; `node` không có trong tài liệu → 404.
    - Thân của `/check` và `/evaluate`: `{workflow_id, node, path, source}`, với `path` là con trỏ JSON tới trường cấu
      hình trong `config` của `node`. Schema của trường đó quyết `source` là gì: một Biểu thức trần với tập kiểu của
      `x-dw-cel`, hay một Chuỗi có biến với đích của `x-dw-sink` (bộ dựng mẫu của ticket 02). Trường không khai cả hai →
      422 `validation_failed`.
    - `/check` trả 200 `{result_type, errors[]}`, với `errors[]` cùng dạng `{path, code, message_vi, message_en}` của bộ
      kiểm.
    - `/evaluate` thêm đúng một trong hai: `sample` (đối tượng người gọi gõ, kiểm theo kiểu của môi trường; khóa lạ hay
      sai kiểu → `expression_error`), hoặc `run_id`. Nó trả 200 `{value}`, hay 422 problem+json mang mã của lỗi
      (ADR-0108 (Accepted)). Biểu thức tính trong môi trường của bước 1 tại `node`, trên nháp hiện tại.
    - Với `run_id`: lượt phải là lượt của chính `workflow_id`, ở phiên bản nào cũng được, không thì 404. Activation là
      `trigger.input` đã ghi của lượt và đầu ra ghi sau cùng của mỗi Bước trội `node` trong lượt đó (lần lặp cuối). Một
      giá trị đã ghi không khớp kiểu của nháp → `expression_error`.
    - Đầu ra đã ghi đọc qua một Protocol hẹp mà ticket này khai trong `dw_studio.workflows`, đáp ứng bằng dịch vụ đọc
      payload Bước chạy của telemetry-and-audit/03 (`GET /api/v1/runs/{run_id}/steps/{step_id}/payload?part=in|out`),
      với cùng luật đọc (`runs.read` hay nhánh người dựng) và cùng phép che theo quyền đọc trường của người gọi; không
      đọc `platform.run_steps` trực tiếp. Lượt không đọc được → 404 giống hệt id không có. Trường bị che không có trong
      activation, nên Biểu thức cần nó trả `field_hidden`.
    - Giới hạn tần suất qua `RateLimiterPort` của usage-and-limits/05, với một khóa mới
      `ExpressionCallerKey(tenant_id, principal_id)` thêm vào `RateLimitKey` (luật "mỗi hình khóa một bên gọi" của
      `dw_platform/application/rate_limit.py`): 60 lần mỗi 60 giây cho `/check` và `/evaluate` cộng lại; lần thứ 61 →
      429 `rate_limited` có `Retry-After`. Port ném lỗi → 503, không bao giờ cho qua. `draft/scope` không bị giới hạn,
      vì nó không tính Biểu thức nào.
    - Không route nào ghi gì, nên không có audit; lần đọc đầu ra đã ghi là lần đọc của telemetry-and-audit/03.
    - Ticket này là bên đọc đầu tiên của `ExpressionEngine` ở API, nên dựng một `CelCppEngine` trong `build_studio`
      (studio-skeleton/02 bước 5) và gọi `aclose()` khi API tắt (ticket 01 bước 6). Sinh lại snapshot OpenAPI và kiểu
      TS.
7. **`effect_door`** (workflow-engine/03; bảng ở mục Trong phạm vi của spec, chủ duy nhất): `data.transform`, `logic.switch`, `flow.stop` khai không cửa; thiếu trường thì sổ từ chối đăng ký, và `incident` của `allowed_on_error` do luật của workflow-engine/07 suy từ trường này, loại không tự khai.

## Tiêu chí chấp nhận

- [ ] R3.2: một Biểu thức tham chiếu một bước phía sau (không trội) → `wf.ref_not_dominating`, không niêm phong; cùng
      tham chiếu bọc trong `has()` → vẫn `wf.ref_not_dominating`; `has(steps.a.error)` với `a` trội khai `continue` →
      qua; Bước trong làn lỗi của `a` đọc `steps.a.error.code` → qua; `trigger.input.amount >` (lỗi cú pháp) →
      `wf.expression_invalid`.
- [ ] R3.3: `on` của một `logic.switch@1` trên đường Studio trả `list`, hay `dyn` từ một trường json →
      `wf.type_mismatch`, không niêm phong; trả `string` → qua; bỏ `x-dw-cel` khỏi schema của `on` → ca `list` niêm
      phong, test đỏ. Lúc chạy, `on` ra `null` → Bước lỗi `expression_error`, làn `default` không chạy.
- [ ] R4.4 (WN5): tham chiếu `phone` của đầu ra bản ghi `lead` (loại fixture) mà người gửi kiểm định không đọc được →
      `field_not_readable`. Lúc chạy, chủ thể chạy không đọc được `phone` → Bước lỗi `field_hidden`, không giá trị nào
      của `phone` trong đầu ra hay lỗi. Gỡ phép `check` lại theo chủ thể chạy, để activation thiếu `phone` tính ra
      `null` → test đỏ.
- [ ] R2.3 (WN11): trên đường gói, một bước không khai Khi lỗi mà lỗi làm lượt `failed`, không đi tiếp; trên đường
      Studio, Bước thiếu `on_error` → `wf.schema_invalid`; `flow.stop@1` hay `logic.switch@1` khai `continue` →
      `wf.config_invalid`; gỡ phép đọc `allowed_on_error` khỏi bộ kiểm → test đỏ.
- [ ] R2.4 (WN11): một `logic.switch` thiếu Nhánh ra mặc định → `wf.router_not_total`, không niêm phong; thêm nhánh mặc
      định → qua.
- [ ] R2.4: `PackCatalog` nạp mọi gói trong `configs/packs`, và `lead_care@1.0.0` biên dịch ra cùng tập node và cạnh
      như snapshot của workflow-engine/01.
- [ ] R1.5: `data.transform@1` với đúng 50 khóa → qua, và Bước sau đọc `steps.t.k50` với kiểu của Biểu thức đó; 51
      khóa → `wf.config_invalid`.
- [ ] R3.2: cây `draft/scope` của một node chỉ liệt kê bước trội và Trường người gọi đọc được; bước phía sau không xuất
      hiện.
- [ ] R3.5: `POST /api/v1/studio/expressions/evaluate` với `trigger.input.amount > 10` và mẫu
      `{"trigger": {"input": {"amount": 11}}}` trả `true` từ máy chủ; với `run_id` của một lượt người gọi đọc được →
      tính trên đầu ra đã che. `/check` trên một trường `x-dw-cel` `["bool"]` với nguồn trả `string` → 200 có lỗi
      `wf.type_mismatch`.
- [ ] R3.5: ở cả ba route, người gọi không giữ `studio.workflows.edit` → 403; người của công ty khác gọi với id quy trình
      này, hay `/evaluate` với `run_id` của công ty khác hay của một quy trình khác → 404 giống hệt id không có; lần gọi
      thứ 61 trong 60 giây tới `/check` và `/evaluate` → 429; gỡ từng kiểm → test của nó đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_variable_scope.py packages/python/dw_studio/tests/workflows/test_logic_nodes.py packages/python/dw_studio/tests/workflows/test_expression_routes.py packages/python/dw_agent_runtime/tests/unit/test_wflite_validate.py` xanh.

## Nguồn

- ADR-0114 (Accepted) quyết 3, 6; spec: R3.2, R3.3, R4.4.
- ADR-0112 (Accepted) quyết 3; spec: R2.4 (bộ kiểm khi gửi kiểm định).
- ADR-0112 (Accepted), Amendments 2026-11-03 (một sổ, làn trong `config`, `wf.unknown_type`) và 2026-11-04 (`has()`);
  spec: R3.2, Quyết định 4/11/2026.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py:73`; spec: R2.4 (`logic.switch@1` đã ship).
- `packages/python/dw_platform/src/dw_platform/application/rate_limit.py:86`; spec: R3.5 (`RateLimiterPort`, mỗi hình
  khóa một bên gọi).

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: mã của các kiểm này là bảng `wf.*` của workflow-engine:R2 (phát hiện A về hai bảng mã); "phát hành" đổi thành "gửi kiểm định" cho bước niêm phong theo bảng thuật ngữ.
- 2026-10-24 (agent): vòng sửa thứ tư: hai mã đổi theo ADR-0112 (Accepted) quyết 3, `wf.ref_not_dominating` và `wf.type_mismatch` (phát hiện CRITICAL F về ADR-0112 (Accepted) và workflow-engine:R2).
- 2026-10-24 (agent): theo V4.24 của Đạt: tài liệu là cây Bước, nên `logic.switch` mang mỗi nhánh thành một làn Bước với làn mặc định "Khác", không còn Đường nối lưu trong tài liệu, và bộ kiểm chạy trên `WorkflowIR` dẫn từ cây. Ba loại điều khiển của bậc B (V4.26) vào ticket 07, không vào ticket này, để workflow-nodes/04, 05, 06, mà marketing-pilot/03 chờ, không chờ bậc B. Không thêm cạnh.
- 2026-10-25 (agent): `flow.stop@1` khai `ends_run` đúng và hai loại kia khai cả ba tính chất vị trí sai, theo trường bắt buộc của ticket 02 (dòng Quyết định 25/10/2026 của spec); phép hạ của workflow-engine/01 đọc `ends_run` để biết Bước nào không có cạnh ra. Không thêm cạnh.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): nhận R3.5 và hai route `/expressions/check`, `/expressions/evaluate` từ
  ticket 01 (gate của ticket 01): không ticket nào dựng chúng, mà route cần môi trường theo vị trí và `draft/scope` của
  ticket này, `studio.workflows.edit` của workflow-engine/01, `RateLimiterPort` và lịch sử chạy; thêm hai chặn tương
  ứng. workflow-builder-ui/03 đã chờ ticket này cho `/expressions/check`. Gate của ticket này kiểm lại phần đó; dòng
  `Xong:` cần thêm test của hai route.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): theo gate của workflow-engine/01: ticket này mang thêm workflow-engine:R2.6
  (`wf.type_mismatch`) và phần `has()` của workflow-engine:R2.5, vì CEL vào bộ kiểm ở đây (spec workflow-engine, Ngoài
  phạm vi). Bộ kiểm là `validate` của lõi `dw_agent_runtime/wflite/validate.py`, `dominators()` là của
  `dw_agent_runtime/wflite/ir.py`, và mã vào `MESSAGES`; kiểm cần dữ liệu Studio (`field_not_readable`) chạy ở
  `dw_studio` trên cùng `WorkflowIR`, qua seam mà ticket này thêm nếu là ticket đầu tiên cần nó.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check cùng boundary walk, vì
  ticket có ba route; không migration). Lượt đầu: 0 CRITICAL, 11 HIGH, đều sửa ở ticket này, spec (Quyết định
  4/11/2026) và ADR-0112 (Accepted) Amendments 2026-11-04:
    - `has()` trên tham chiếu không trội không phân biệt được với tham chiếu trần khi binding không lộ AST: nay mọi tham
      chiếu không trội bị từ chối, `has()` chỉ cho trường tùy chọn của Bước trội.
    - Chủ thể của `visible_fields` lúc gửi kiểm định và lúc chạy chưa định nghĩa; lúc chạy, Biểu thức (không chỉ mẫu)
      gặp Trường bị ẩn chưa có hành vi. Nay: người gọi lúc gửi kiểm định, chủ thể chạy lúc chạy, `field_hidden`, không
      `null`.
    - `/evaluate` trên đầu ra đã ghi không nói quyền, cách che hay lượt nào: nay qua dịch vụ đọc payload của
      telemetry-and-audit/03, 404 khác tenant.
    - `logic.switch@1` của wf-lite (`on` là tra giá trị) mâu thuẫn với "điều kiện `bool`": nay sửa tại chỗ, `on` vô
      hướng, ca `bool` của R3.3 ở ticket 07 với `x-dw-cel`.
    - Phép ánh xạ payload bằng CEL ở ingress có hai chủ (ticket này và workflow-triggers): bỏ khỏi W1.
    - Thân request của `/check`, `/evaluate`, và 404 cho `node` không có.
    - Khi lỗi cho phép, `block`, `dependencies` của ba loại, và trạng thái lượt sau `flow.stop`: nay khai, cùng trường
      `allowed_on_error` ở ticket này.
    - Hình cấu hình và đầu ra của `data.transform@1`, mã cho khóa thứ 51.
    - Giới hạn tần suất không có số, khóa hay hành vi khi port lỗi: nay 60 lần mỗi 60 giây theo `(tenant, người gọi)`,
      503 khi port lỗi.
    - Test âm 403 và 404 khác tenant chỉ có ở `/evaluate`, và dòng `Xong:` thiếu test route.
    - `studio_node_types(ports)` và tham số `extra` mà ticket 02 giao cho ticket này không có bước nào.
- 2026-11-04 (agent): MEDIUM của gate, cho người làm và cho `checking-plan-consistency`:
    - (a) Pool hai tiến trình tính của ticket 01 dùng chung mọi tenant với hàng FIFO không trần; một tenant dưới giới
      hạn tần suất vẫn có thể làm chậm tenant khác. Đo ở lúc đóng hàng đợi; trần hàng chờ nếu số đo xấu.
    - (b) Hai tên cho một lỗi: `field_hidden` (R4.4 của spec này) và `template_field_hidden` (field-security:R4.3).
    - (c) Ai đăng ký loại trình kích hoạt của Nguồn dữ liệu trong `NodeTypeRegistry` (workflow-triggers/02 hay
      workflow-engine), và trình kích hoạt khai lược đồ đầu vào ra sao trong `triggers[]`; ticket này chỉ đọc lược đồ đó.
    - (d) `aclose()` của `CelCppEngine` khi API tắt không có tiêu chí riêng; test vòng đời của `build_studio` nên phủ.
    - (e) Mục "môi trường" cũ có `item`/`index` của thân map, W2; đã bỏ.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 10 câu, sửa theo khuyến nghị:
    - `field_hidden` lúc chạy sinh bằng `check` lại theo Trường chủ thể chạy đọc được, vì trường vắng đọc ra `null`;
      Trường nào bị lọc là Trường của giá trị kiểu bản ghi, test dùng loại fixture;
    - lỗi biên dịch khác tham chiếu không trội → `wf.expression_invalid` (mã mới);
    - thân `/check` có `path` tới trường cấu hình, hình phản hồi của hai route;
    - `draft/scope` không bị giới hạn tần suất;
    - `incident` vào tập Khi lỗi cùng workflow-engine/07; `human.approval@1` nhận `fail`, `route` ngay từ ticket này;
    - trên đường Studio, Bước thiếu `on_error` → `wf.schema_invalid`;
    - `/evaluate` với `run_id`: lượt của chính quy trình, activation từ đầu ra ghi sau cùng;
    - `on` ra `null` → `expression_error`, không làn `default`; `dyn` → `wf.type_mismatch`;
    - đường `trigger.input.<trường>`, và kiểu khi tài liệu có nhiều trình kích hoạt;
    - lúc gửi kiểm định, chủ thể chạy là người gửi tới khi điểm gắn run-as vào tài liệu (ADR-0114 (Accepted) quyết 4).

    Không còn CRITICAL hay HIGH.

- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): theo gate của ticket 05 và 06: tập `refused_types` của `PathRules` vào
  ticket này (rỗng), vì ticket 05 và 06 cùng thêm vào nó mà không chờ nhau, nên phần chung nằm ở ticket sớm nhất; Bước
  phê duyệt của Studio là `human.approval@2` của ticket 06, nên `allowed_on_error` của sáu loại wf-lite là `fail`,
  `continue`, `route`. Không thêm cạnh.
