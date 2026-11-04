# 01 — Executor tự kiểm JSON Schema, phân giải theo tenant, khe nhà máy theo loại

Status: resolved (2026-11-02, main)
Blocked by: .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R3.1, R3.2, G1, G2, G3, G4, G5, G6, TS2, TS3, TS4, TS5, TS6, TS10, TS12, TS13

## Mục tiêu

Executor tự kiểm đầu vào và đầu ra bằng JSON Schema (LangChain không kiểm lược đồ dạng dict), phân giải
công cụ theo công ty, một nhà máy theo Loại công cụ với Mức sàn theo loại mà công ty chỉ siết, một nơi
quyết duyệt, sàn gửi tin đã có (compliance-pdpl/08) giữ cho mọi công cụ có khối `message`, và một sổ bước có thứ tự
cho `ToolExecutor` ở bộ dựng chung của hai root, nơi mỗi ticket chủ đăng ký bước của mình (spec R1, R2, R3; H-3). Mọi loại công cụ
Studio sau này thừa hưởng một cửa này. Gộp từ B8b-tools tools-and-skills 02; đóng đường vòng quanh executor đã nằm ở
runtime-hardening/01.

## Việc cần làm

1. Kiểm JSON Schema của công cụ ở bộ kiểm duy nhất của nền tảng,
   `packages/python/dw_platform/src/dw_platform/application/json_schema.py` (đã có `jsonschema==4.26.0` ghim ở
   `dw_platform`, mà runtime đã nhập qua wf-lite), không module kiểm thứ hai và không phụ thuộc `jsonschema` trực
   tiếp ở `dw_agent_runtime`: thêm vào module đó một lối vào cho công cụ (Draft 2020-12, `FormatChecker` danh sách
   đóng có `phone_vn`, `tax_code_vn`, `referencing.Registry()` rỗng, lỗi chỉ nêu `path` và từ khóa lược đồ, không bao
   giờ giá trị, khác `problems()` hôm nay vốn trả `error.message` có giá trị); `dw_agent_runtime/tool_schema.py` chỉ
   giữ `check_profile(schema)` (hồ sơ `dw.tool-schema/v1` của ADR-0116 (Accepted) quyết 3: gốc là object,
   `additionalProperties: false`, sâu tối đa 5, tối đa 100 thuộc tính, không `$ref`, `allOf`, `oneOf`, `not`, điều
   kiện hay `pattern`) và gọi lối vào đó.
2. `ToolBehaviour(validate_input, validate_output, handler, approval_preview)`: bản Pydantic cho công cụ
   định nghĩa bằng code (giữ G1), bản JSON Schema cho công cụ dữ liệu tenant. Mọi chỗ hôm nay đọc
   `tool.input_model` hay `tool.output_model` đi qua `ToolBehaviour`: kiểm đầu vào
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:304`), trường hủy nhận của sàn gửi tin
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:484`, chèn ở
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:389`), phát lại
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:541`), kiểm đầu ra
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:601`) và mẫu giả lập
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:860`, `sample_of` nhận output JSON Schema).
3. `ToolRegistry.register(tool, *, tenant_id: TenantId | None = None)` và `ToolRegistry.resolve(name, version, *,
tenant_id: TenantId | None)` theo khóa `(tenant_id, name, version)`: `None` là lớp nền tảng; một `tenant_id` tìm
   mục của đúng công ty đó rồi lớp nền tảng, không bao giờ mục của công ty khác (`not_found`); `has_tool`,
   `all_definitions` và `definitions_for` chỉ đọc lớp nền tảng (câu trả lời kho không tùy người hỏi, `CLAUDE.md`
   "Per-tenant artifacts"). `ToolExecutor` resolve bằng `run_context.tenant_id`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:299`), mọi lời gọi khác của `resolve` hôm nay
   (như `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:492`, lúc dựng agent)
   truyền `tenant_id` tường minh. Ở W1 chưa ai đăng ký mục của công ty ngoài test; ticket 03 đăng ký công cụ đối
   tượng của công ty. Lượt chạy Studio chỉ dùng phiên bản công cụ đã ghim trong bản kê lượt chạy, không rơi về lớp
   nào lúc chạy (DO-05; bộ lắp của ticket 02 truyền phiên bản ghim).
4. `ToolKindFactory.build(binding, contract, deps) -> ToolBehaviour`, một bảng `kind -> factory` ở
   composition root, một bộ lắp duy nhất tạo `RegisteredTool`; W1 có `object_crud` và `connector_action`.
5. `KIND_FLOORS` và `check_policy_against_floor(policy, floor)` dùng cho Mức sàn theo loại và ghi đè; chỉ siết, không
   hạ; hàm thuần, từ chối bằng lỗi `validation_failed` mang `details.reason_code` `kind_floor_violation` (422 qua
   phong bì lỗi của ADR-0108 (Accepted)), theo ADR-0116 (Accepted) quyết 1. Bên đọc ở W1 là bộ lắp duy nhất của bước 4:
   một công cụ nền tảng hay một Hành động có chính sách dưới sàn của loại thì bộ lắp trả `ConfigError`, công cụ không
   được đăng ký. Lệnh lưu và gửi kiểm định công cụ của công ty (route, 422 của R2.3) và lệnh ghi đè công cụ nền tảng
   của công ty (R2.4) là W2, gọi đúng hàm này (Ngoài phạm vi của spec, hai dòng W2 về loại `tool` và về công cụ nền
   tảng chỉ siết); ticket này không dựng route nào.
6. `ToolExecutor.approval_required(definition, run_context) -> bool` là câu trả lời duy nhất cho "lời gọi này có chờ
   người không": `approval_policy.decide(definition, run_context)` và lời gọi không bị chế độ chạy chặn
   (`not definition.intercepted_in(run_context.run_mode)`). Hôm nay ba cổng mỗi nơi tự ghép hai vế đó: executor
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:350`), `OneApprovalPerStepMiddleware`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:277`) và wrapper công cụ
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:501`); sau ticket này
   middleware và wrapper chỉ gọi `executor.approval_required`, không tự đọc `approval_policy` hay `intercepted_in`.
   `args` và `step_calls` của ADR-0116 (Accepted) quyết 3 vào chữ ký cùng bên đọc của chúng, điều kiện duyệt và cờ
   nhiễm ở W2 (dòng W2 thứ ba của Ngoài phạm vi; ADR-0116 (Accepted) quyết 1, mỗi trường vào cùng bên đọc nó).
7. Sàn gửi tin đã có (compliance-pdpl/08): `SendAdmissionPort` khai ở
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:146`, bước 4b ở
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:382`, cả hai root dựng sàn qua
   `build_send_floor` và truyền vào `build_tool_executor(send_admission=...)`. Ticket này giữ nguyên hành vi đó (G5) và
   đưa nó vào sổ như một bước đã đăng ký (bước 8), không phải bước chờ. Dấu của công cụ gửi tin là khối `message`
   (`ToolDefinition.message`, từ `ToolSpec.sends_message`), không thêm dấu thứ hai; `effect_class: message` của một
   Hành động `connector_action` dịch thành khối đó ở bộ lắp (connections-and-vault/05). Sửa một đường vòng: hôm nay sàn
   chỉ chạy khi có khóa chống lặp (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:382`), mà khóa chỉ
   bắt buộc với mức `external`, `critical`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:368`), nên một công cụ `internal` có khối
   `message` gọi không khóa sẽ đi qua không hỏi sàn; khóa nay bắt buộc cả với mọi công cụ có khối `message`. Lần từ chối
   của sàn: `MarketingSendPolicy` ghi dòng `blocked` và `marketing.send_refused` trong giao dịch của chính nó
   (compliance-pdpl:R3.1, compliance-pdpl:R3.7); executor ghi dòng `refused` và `tool.denied` mang `reason_code`
   `blocked:<lý do>` như mọi lần từ chối khác của nó (`_refuse`), không ghi `marketing.send_refused` thứ hai.
8. Sổ bước của `ToolExecutor` (R2.6, R2.7; H-3): một hàm duy nhất `build_tool_executor_steps(deps)` cạnh
   `build_tool_executor` trong `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/wflite_host.py`, mà
   `build_tool_executor` gọi, nên API (`apps/api/src/dw_api/bootstrap/runtime.py:208`) và worker
   (`apps/worker/src/dw_worker/composition.py:316`) có sổ chỉ qua bộ dựng duy nhất chúng đã gọi, không root nào gọi hàm
   thứ hai; `deps` là các tham số `build_tool_executor` nhận hôm nay. Sổ khai các bước theo đúng thứ tự R2.6: công tắc
   điều khiển, phân giải, kiểm đầu vào, biên Digital Worker, lời gọi quyết định, kiểm quyền, chế độ chạy, phê duyệt,
   sàn gửi tin, giành lượt, ghi `dispatched`, gọi handler, kiểm đầu ra, audit. Đã đăng ký: mọi bước trừ công tắc điều
   khiển, tức các bước của ticket này, biên Digital Worker (digital-worker:R6.1, `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:316`), lời gọi quyết định
   (wf-lite:R6.17, `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:322`), chế độ chạy (tenant-config/03, `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:348`), sàn gửi tin
   (compliance-pdpl/08, bước 7) và giành lượt, ghi `dispatched` (runtime-hardening/01); danh sách bước chờ đăng ký chỉ
   có công tắc điều khiển, nêu đường dẫn `.claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md`.
   Hình của bước: một bước cổng là `async (call: ToolCall) -> BaseModel | None`, trả `None` thì đi tiếp, trả một kết quả
   thì lời gọi kết thúc với kết quả đó (mẫu của chế độ chạy, kết quả phát lại), ném lỗi thì từ chối; `ToolCall` là trạng
   thái của một lời gọi (công cụ, `ToolBehaviour`, đầu vào đã kiểm, `input_hash`, `approved`, biên DW, khóa, `sending`,
   `token`), và một bước cần việc sau (sàn gửi tin gọi `send_admission.sent` khi thành công, giành lượt nhả claim trong
   `finally`) gắn việc đó vào `ToolCall` để `_execute` chạy. Năm bước cuối, từ giành lượt tới audit, là đuôi của
   executor (`_run` hôm nay: kiểm đầu ra trong từng lần thử của vòng thử lại, `outcome_unknown`, ghi dòng và audit), có
   tên trong sổ theo đúng thứ tự R2.6 nhưng chỉ executor đăng ký; khóa chống lặp bắt buộc (bước 7) thuộc bước phê
   duyệt. `ToolExecutor._execute` chỉ chạy các bước của sổ theo thứ tự đó, không gọi bước nào ngoài sổ; đăng ký một tên
   ngoài R2.6, một tên hai lần, hay một tên đuôi từ ngoài executor là `ConfigError` lúc khởi động; ghi thứ tự ở docstring
   đầu `executor.py` thay chuỗi cũ. Test sổ: so tên các bước với dãy R2.6 và đỏ, nêu bước, khi hai bước ngược thứ tự,
   có tên lạ, hay vắng một bước không có trong danh sách chờ. Ở chế độ khác `live`, lời gọi bị giả lập dừng ở bước chế
   độ chạy, nên không gọi `approval_required` và không mở phê duyệt (tenant-config:R5.6; ADR-0111 (Accepted) quyết 5).
9. Bước sàn gửi tin không có sàn (R2.8): khi `build_send_floor` trả `None` (thiếu `UNSUBSCRIBE_SIGNING_SECRET`), mọi
   lời gọi tới công cụ có khối `message` trả kết quả bị chặn `blocked:send_floor_unavailable`, không gọi handler, như
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:490` hôm nay; bước đó vẫn là bước đã đăng ký của
   sổ.

## Tiêu chí chấp nhận

- [x] R1.1 (TS2): gọi thẳng executor với `{"lead_id": 1, "amount": -5, "extra": "x"}` cho công cụ dữ
      liệu tenant → `validation_failed` nêu `path`, handler (spy) không chạy; gỡ bước kiểm lược đồ → test
      đỏ.
- [x] R1.2 (TS3): handler trả trường ngoài lược đồ hay sai kiểu → `tool_output_invalid`, model không
      nhận đầu ra; gỡ bước kiểm đầu ra → test đỏ.
- [x] R1.3 (TS2): đầu vào có trường ngoài lược đồ → `validation_failed`, handler không chạy.
- [x] R2.1: công cụ đăng ký cho công ty A, lượt chạy của công ty B gọi cùng tên và phiên bản → `not_found`, handler
      không chạy; lượt của A → chạy; công cụ nền tảng cùng tên khi B không có mục riêng → B nhận bản nền tảng, không
      bao giờ bản của A; `has_tool` và `definitions_for` không thấy mục của A; resolve bỏ `tenant_id` khỏi khóa → test
      đỏ.
- [x] R2.2: bảng `kind -> factory` ở composition root có `object_crud` và `connector_action`, mỗi mục trả một
      `ToolBehaviour` mà bộ lắp dựng thành `RegisteredTool` (nhà máy giả trong test; nhà máy thật là của ticket 03 và
      connections-and-vault/05); một loại không có trong bảng → `ConfigError`, không công cụ nào được đăng ký.
- [x] R2.3 (TS4): bảng ca của `check_policy_against_floor`: `http` POST với Mức tác động `none` →
      `kind_floor_violation`; bộ lắp dựng một công cụ có chính sách dưới sàn của loại → `ConfigError`, công cụ không
      được đăng ký; gỡ kiểm sàn → test đỏ.
- [x] R2.4 (TS4): bảng ca của cùng hàm: chính sách nền tảng `always`, ghi đè `conditional` → `kind_floor_violation`;
      ghi đè `conditional` lên `always` → nhận; ghi đè đúng bằng sàn → nhận.
- [x] R2.5 (TS5): gọi executor với `approved=False` cho công cụ cần duyệt, bỏ qua wrapper → `approval_required`,
      handler không chạy; spy trên `executor.approval_required` thấy wrapper và `OneApprovalPerStepMiddleware` gọi nó
      cho mỗi lời gọi được hỏi; cho `approval_required` trả `True` với một công cụ mà `approval_policy.decide` không
      chặn → cả wrapper lẫn middleware hỏi người; middleware tự đọc `approval_policy` thay vì gọi
      `executor.approval_required` → test đỏ.
- [x] R2.6 (TS10): bảng ca gọi thẳng executor, mỗi ca từ chối ở một bước (phân giải, đầu vào, biên Digital Worker, lời
      gọi quyết định, quyền, chế độ chạy, phê duyệt, sàn gửi tin, giành lượt) → spy của mọi bước sau không được gọi,
      không dòng `dispatched` nào, handler không chạy; lời gọi qua mọi bước → dòng `dispatched` có trước lời gọi
      handler; công cụ `critical` cần duyệt gọi ở `simulate` → lời gọi `simulated`, không `approval_required`, không
      dòng `platform.approval_requests` nào, còn ở `live` → `approval_required`; đảo hai bước liền nhau, kể cả chế độ
      chạy và phê duyệt, hay biên Digital Worker và kiểm quyền → test đỏ.
- [x] R2.7 (TS12): sổ thử đảo bước chế độ chạy và bước phê duyệt, thêm một bước không có tên trong R2.6, đăng ký một
      tên đuôi từ ngoài executor, hay bỏ bước phân giải mà không đưa vào danh sách chờ → test sổ đỏ, nêu bước;
      `build_tool_executor` dựng sổ bằng `build_tool_executor_steps`, API và worker dựng executor chỉ qua
      `build_tool_executor`, và gỡ một dòng đăng ký của hàm đó → test đỏ; `_execute` gọi một bước ngoài sổ → test đỏ;
      sổ thật của ticket này, danh sách chờ chỉ có công tắc điều khiển → xanh; đưa bước sàn gửi tin về danh sách chờ →
      test sổ đỏ.
- [x] R2.8 (TS13): bộ dựng không có sàn (`send_admission=None`), gọi `email.send` (khối `message`) →
      `blocked:send_floor_unavailable`, handler (spy) không chạy, không dòng `dispatched` nào; một công cụ không có
      khối `message` → chạy như thường; cho lời gọi đi qua khi không có sàn → test đỏ.
- [x] R3.1 (TS6): công cụ có khối `message` → executor hỏi `SendAdmissionPort` trước mỗi lời gọi (spy thấy một lần
      mỗi lời gọi, kể cả hai lời gọi liền nhau cùng người nhận); công cụ mức `internal` có khối `message` gọi không khóa
      chống lặp → bị từ chối, sàn không được hỏi, handler không chạy (hôm nay lời gọi đó chạy); bỏ khối `message` khỏi
      điều kiện khóa bắt buộc → test đỏ.
- [x] R3.2 (TS6): lead không có đồng ý đúng mục đích → `email.send` không gọi nhà cung cấp, kết quả bị chặn
      `blocked:no_consent`, một dòng `refused` và một `tool.denied` mang `reason_code` đó, không `marketing.send_refused`
      nào do executor ghi (một, của `MarketingSendPolicy`); gỡ bước sàn gửi tin khỏi sổ → test đỏ.
- [x] G1: `test_happy_path_returns_typed_output_and_audits` và mọi test executor hiện có xanh.
- [x] G2: `test_replay_returns_cached_output_without_reexecution` xanh (phát lại theo khóa chống lặp
      không chạy lại handler).
- [x] G3: `test_a_dw_run_outside_its_boundary_reaches_nothing` xanh sau khi biên Digital Worker vào sổ.
- [x] G4: `test_a_decision_above_its_level_needs_this_runs_matching_approval` xanh sau khi lời gọi quyết định vào
      sổ.
- [x] G5: `test_a_send_without_consent_is_refused_at_the_executor` và mọi test của
      `packages/python/dw_agent_runtime/tests/integration/test_send_floor_executor_db.py` xanh sau khi sàn gửi tin vào
      sổ.
- [x] G6: `test_a_send_with_no_known_outcome_is_never_made_again` xanh sau khi giành lượt vào sổ.
- [ ] Xong: `make ci && make test-integration` xanh (theo `wave-close.md`: cổng nhanh và integration của ticket đã chạy; toàn bộ `make test-integration` chạy lúc đóng đợt).

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:303`; spec: R1.1, G1.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:601`; spec: R1.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:350`; spec: R2.5.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:3`; spec: R2.6 (chuỗi bước cũ ở
  docstring).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:298-461`; spec: R2.6, G3-G6 (thứ tự thật hôm
  nay: phân giải, đầu vào, biên DW 2b, quyết định 2c, quyền, chế độ 3b, phê duyệt, khóa bắt buộc, sàn 4b, giành lượt
  5, ghi `dispatched` 6, handler 7, đầu ra 8, ghi và audit 9).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/wflite_host.py:103`; spec: R2.7.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/tools.py:45`; spec: R2.1.
- `packages/python/dw_platform/src/dw_platform/application/json_schema.py:1`; spec: R1.1, R1.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:36-50`; spec: R2.3, R2.4.
- spec: R1, R2, R3, TS2-TS6, TS12, TS13; H-3; ADR-0116 (Accepted) quyết 1, 3; ADR-0124 (Accepted) quyết 2;
  runtime-hardening/01 (`ToolClaimPort`, CHECK `tool_executions.status`, dòng `dispatched`, runtime-hardening:R6.11);
  tenant-config/03 (bước chế độ chạy, tenant-config:R5.1); compliance-pdpl/08 (sàn gửi tin, compliance-pdpl:R3.1);
  digital-worker:R6.1; wf-lite:R6.17.

## Comments

- 2026-10-23 (agent): brief ticket 01 (đóng đường vòng, ghim deepagents, test hợp đồng) đã gộp vào
  runtime-hardening/01; ticket này là brief ticket 02 cộng hook sàn gửi tin
  (YC86, ADR-0124 (Accepted)).
- 2026-10-23 (agent): thêm R2.6 (thứ tự bước một chủ) và Blocked by tenant-config/03 theo phát hiện kiểm
  nhất quán cùng ngày, vì cả hai ticket viết lại chuỗi bước của `ToolExecutor._execute`; audit từ chối của
  sàn gửi tin là `marketing.send_refused` của compliance-pdpl, `tool.simulated` là của tenant-config:R5.2.
  Theo DO-05 (Đạt, 23/10/2026), lượt chạy Studio chỉ dùng phiên bản đã ghim (bước 3).
- 2026-10-24 (agent): theo quyết định Đạt ngày 24/10/2026: N2 đặt bước chế độ chạy trước bước phê duyệt (bước 8;
  R2.6, TS10; hành vi giả lập không mở phê duyệt là tenant-config:R5.6); Mức sàn kiểm lúc lưu và lúc gửi kiểm
  định (bước 5, R2.3); thêm Blocked by agent-lifecycle/01, vì ticket đó chèn bước công tắc vào cùng chuỗi bước
  của `ToolExecutor._execute`.
- 2026-10-25 (agent): lượt h, theo V4.30, V4.31 của Đạt và H-3: ticket này dựng sổ bước có thứ tự ở composition root
  (bước 8; R2.7, TS12), thứ tự R2.6 có bước ghi `dispatched` ngay trước bước gọi handler (runtime-hardening:R6.11), và
  bước sàn gửi tin còn chờ đăng ký thì chặn Hành động `message` (bước 9; R2.8, TS13). Gỡ cạnh Blocked by
  agent-lifecycle/01: ticket đó nay chờ ticket này và chỉ thêm một dòng đăng ký vào sổ.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate CRITICAL C1: R2.6 không có biên Digital Worker (bước 2b,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:316`) và lời gọi quyết định (bước 2c, `:322`), mà
  sổ từ chối mọi tên ngoài R2.6 và `_execute` chỉ chạy bước của sổ, nên dựng theo chữ là bỏ kiểm biên DW và kiểm phê
  duyệt quyết định (digital-worker:R6.1, wf-lite:R6.17). Sửa: R2.6 theo thứ tự thật của mã (biên DW và lời gọi quyết
  định giữa kiểm đầu vào và kiểm quyền), bước 8 đăng ký cả hai, tiêu chí R2.6 có hai ca từ chối của chúng, G3, G4 giữ
  test của chúng, G6 giữ `outcome_unknown`; neo ở bước 2, 3, 6 và Nguồn sửa theo mã hôm nay (`:146` thành `:299`,
  `:135` thành `:350`, `:151` thành `:303`, `:236` thành `:601`). Nếu sai thì: hai bước đó đứng chỗ khác trong R2.6
  và bước 8 dời chúng cùng test của G3, G4.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B1 (sàn gửi tin): bước 7, 9 và R2.8, R3.1, R3.2 viết như
  thể sàn chưa có, trong khi compliance-pdpl/08 (đã xong) đã cài nó ở bước 4b và cả hai root truyền
  `build_send_floor(...)` vào `build_tool_executor`; đưa nó về danh sách chờ như bước 8 cũ viết là chặn mọi
  `email.send` ở cả hai root. Thêm: dấu thật là khối `message`, không `effect_class`; audit thật là `marketing.send_refused`
  trong giao dịch của policy cộng `refused` và `tool.denied` của executor, nên tiêu chí "executor không tự ghi audit
  nào" sẽ đỏ trên mã đã xong; và một đường vòng: sàn chỉ chạy khi có khóa, mà khóa chỉ bắt buộc với `external`,
  `critical`. Sửa: bước 7, 9, sàn là bước đã đăng ký, danh sách chờ chỉ có công tắc điều khiển, khóa bắt buộc với mọi
  công cụ có khối `message`, tiêu chí R2.7, R2.8, R3.1, R3.2, G5; spec R2.8, R3.1, TS6, TS13, Trong phạm vi, Phụ thuộc.
  Nếu sai thì: compliance-pdpl/08 gỡ sàn khỏi `_execute` cùng lúc compliance-pdpl/04 đăng ký nó, và R2.8 trở lại "còn
  chờ đăng ký".
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B2 (chỗ dựng sổ): bước 8 nêu `wiring.py` và `main.py`, nhưng
  API dựng executor ở `apps/api/src/dw_api/bootstrap/runtime.py:208` và worker ở
  `apps/worker/src/dw_worker/composition.py:316`, cả hai qua `build_tool_executor` của `wflite_host`. Sửa: bước 8 đặt
  `build_tool_executor_steps` cạnh `build_tool_executor`, được nó gọi; tiêu chí R2.7 kiểm hai root chỉ qua bộ dựng đó.
  Nếu sai thì: mỗi root gọi `build_tool_executor_steps` và test sổ so hai bản.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B3 (hình của bước): bước 8 không nói một bước là gì, trong
  khi các bước hôm nay chia trạng thái (biên DW cho lời gọi quyết định, `approved`, đầu vào có link hủy, `sending`,
  `token`), kết thúc sớm (mẫu, phát lại) và có việc sau (`sent`, nhả claim). Sửa: bước 8 định nghĩa bước cổng
  `async (call: ToolCall) -> BaseModel | None` và việc sau gắn vào `ToolCall`, năm bước cuối là đuôi chỉ executor đăng
  ký; bước 2 liệt kê mọi chỗ đọc `input_model`, `output_model` phải qua `ToolBehaviour`. Nếu sai thì: người dựng chọn
  hình khác giữ cùng ba lối ra (đi tiếp, kết thúc với kết quả, từ chối) và cùng việc sau.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B4 (bộ kiểm thứ hai): bước 1 tạo `JsonSchemaValidator` và
  phụ thuộc `jsonschema` trong runtime, trong khi `packages/python/dw_platform/src/dw_platform/application/json_schema.py`
  là "the one JSON Schema validator" mà wf-lite đã dùng (`CLAUDE.md`: "checked by the platform's validator";
  `failure-modes.md` #2). Sửa: bước 1 thêm lối vào cho công cụ ở module đó (lỗi chỉ nêu path và từ khóa, vì `problems()`
  hôm nay trả `error.message` có giá trị), `tool_schema.py` chỉ giữ `check_profile`. Nếu sai thì: module riêng trong
  runtime và một test chứng minh hai bộ kiểm cùng nhận và cùng từ chối trên một bảng ca.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B5 (sàn theo loại không có route ở W1): tiêu chí R2.3, R2.4
  đòi 422 lúc lưu, gửi kiểm định và ghi đè, mà W1 không có route lưu công cụ nào và ghi đè công cụ nền tảng là dòng W2
  của Ngoài phạm vi. Sửa: bước 5 là hàm thuần, bên đọc W1 là bộ lắp (`ConfigError`), route là của hai dòng W2; tiêu chí
  là bảng ca của hàm và ca bộ lắp. Nếu sai thì: ticket này dựng route lưu công cụ ở W1.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B6 (lớp công ty của `ToolRegistry`): bước 3 không nói mục của
  công ty vào sổ thế nào, khóa là gì, và `has_tool`, `definitions_for` đọc lớp nào. Sửa: `register(..., tenant_id=None)`,
  khóa `(tenant_id, name, version)`, rơi về lớp nền tảng không bao giờ sang công ty khác, câu trả lời kho chỉ đọc lớp
  nền tảng; tiêu chí R2.1 có ca chéo công ty và ca kho. Nếu sai thì: mục của công ty nằm trong một sổ riêng theo lượt.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B7 (`approval_required` đã một nửa có): ba cổng hôm nay đã
  cùng gọi `AutonomyApprovalPolicy.decide` (`executor.py:350`, `langchain_tools.py:277`, `:501`), nên tiêu chí "ba cổng
  cho cùng kết quả" xanh sẵn ở commit gốc; còn hai bản ghép `decide` với `intercepted_in` ở middleware và wrapper.
  Sửa: bước 6 là một phương thức `approval_required(definition, run_context)` mà middleware và wrapper gọi; `args`,
  `step_calls` vào ở W2 cùng bên đọc (ADR-0116 (Accepted), sửa đổi 2026-11-02); tiêu chí R2.5 đỏ khi middleware tự
  đọc policy. Nếu sai thì: chữ ký bốn tham số từ W1.
- 2026-11-02 (agent): ghi chú MEDIUM và LOW của gate cho người dựng, chưa sửa: (M1) `tool_output_invalid` không có trong
  `ErrorCode` (`packages/python/dw_kernel/src/dw_kernel/errors.py:16` chỉ có `validation_failed`); nên là
  `details.reason_code` của `validation_failed` như `kind_floor_violation`. (M2) Định dạng `phone_vn`, `tax_code_vn`
  chưa có quy tắc chép từ spec (số chữ số, tiền tố); người dựng lấy từ custom-objects và ghi lại. (M3) Mục công ty của
  `ToolRegistry` nằm trong một dict cả tiến trình: cái gì gỡ chúng (`failure-modes.md` #6) là câu hỏi của ticket 03,
  người đăng ký đầu tiên. (M4) compliance-pdpl:R3.12, CP25 và mục tiêu của compliance-pdpl/04 còn nói ticket 04 đăng ký
  sàn vào sổ thay lời từ chối khi chờ; sau B1 điều đó đã sai, `checking-plan-consistency` của khu vực phải sửa
  compliance-pdpl (gate này không sửa spec khác). (M5) "Hiện trạng" của spec đọc ở `ab33703`, trước sàn gửi tin và bộ
  kiểm JSON Schema của nền tảng; các dòng Quyết định 2/11/2026 thay cho việc đọc lại. (M6) record-access/04 sửa
  `RunContext` và đường công cụ của runtime, không có đường phụ thuộc với ticket này; không chung bảng, route,
  migration, config hay prompt (không phải va chạm theo `ticket-template.md`), nhưng cùng tệp mã: ai sau thì rebase.
  (M7) Tiêu chí R2.2 chỉ chứng minh được bằng nhà máy giả, vì nhà máy thật là của ticket 03 và
  connections-and-vault/05. (M8) Dòng `Xong:` đọc theo `wave-close.md`: cổng nhanh cộng integration của
  `dw_agent_runtime`, `dw_platform`, `apps/api`, `apps/worker`. (L1) Công tắc điều khiển còn chờ thì không chặn gì
  (spec, 25/10/2026), dù ADR-0116 (Accepted) quyết 3 nói từ chối trước phân giải; đúng khi agent-lifecycle/01 đăng ký.
- 2026-11-02 (agent): ticket này không thêm migration và không đổi câu lệnh nào trên đường request (sổ bước, phân giải
  và `approval_required` chạy trong bộ nhớ; kiểm JSON Schema là CPU), nên không thuộc diện đo của `latency.md` ("When");
  lời gọi công cụ đo cùng đợt ở lúc đóng wave.
- 2026-11-02 (agent): lượt xác nhận của gate, chỉ đọc chỗ sửa C1 và B1-B7: không CRITICAL mới; bước 1-9, tiêu chí,
  Nguồn, ADR-0116 (Accepted) (sửa đổi 2026-11-02) và R2.6, R2.8, R3.1, G3-G6, TS6, TS13, Trong phạm vi, Phụ thuộc của
  spec cùng nói một điều. Hệ quả ngoài khu vực này, chưa sửa: compliance-pdpl:R3.12, CP25 (M4).
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `build_tool_executor_steps()` không nhận `deps`, và một bước là
  `async (executor, call) -> BaseModel | None` (phương thức `ToolExecutor.step_*` chưa gắn), không phải
  `async (call)`: bước tới cổng của nó qua executor đang chạy, nên sổ là dữ liệu dựng một lần, không vòng tròn
  executor-sổ; ba lối ra và việc sau giữ như bước 8 (`ToolCall.after_success` cho `sent`, nhả claim ở đuôi).
  `ToolExecutor.steps` là trường bắt buộc, `seal()` chạy ở `__post_init__`. Nếu sai thì: bước nhận closure trên
  `deps` và `build_tool_executor_steps(deps)` dựng chúng trước executor.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `ToolKindFactory.build(binding, contract)` không có `deps`:
  nhà máy nhận phụ thuộc qua constructor (`CLAUDE.md`: constructor injection, không service locator). Bảng
  `kind -> factory` là tham số `kinds` của bộ lắp duy nhất `ToolAssembler` (`tool_kinds.py`); hai root chưa dựng
  bộ lắp vì W1 chưa có nhà máy thật nào (ticket 03, connections-and-vault/05 mang chúng và dòng ở root), và một
  mục giả ở root là placeholder (`failure-modes.md` #1). Nếu sai thì: `wflite_host` thêm `build_tool_assembler`
  mà hai root gọi với bảng rỗng.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `KIND_FLOORS` khóa theo `(kind, read|write)`: `object_crud` đọc
  `none/never`, ghi `internal/conditional`; `connector_action` và `http` đọc `none/never`, ghi
  `external/conditional`; phương thức `http` khác GET, HEAD luôn là ghi, và một binding không nói là ghi (đóng khi
  thiếu). Loại không có trong bảng (`mcp`, `workflow`, `code`) bị bộ lắp từ chối tới khi ticket của nó ghi sàn.
  Ghi đè công cụ nền tảng: `assemble(..., over=<định nghĩa nền tảng>)` lấy chính sách nền tảng làm sàn thứ hai.
  Nếu sai thì: đổi số trong bảng, hàm và bộ lắp không đổi.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): M1 theo khuyến nghị: `tool_output_invalid` là
  `details.reason_code` của `validation_failed`. Với công cụ mức `external`, `critical`, đầu ra sai lược đồ sau khi
  lời gọi đã rời nền tảng vẫn là `outcome_unknown` (runtime-hardening R6.12), không phải `tool_output_invalid`:
  hiệu ứng có thể đã xảy ra, và cả hai đều không đưa đầu ra cho model. M2: `phone_vn` là di động 0 rồi 3, 5, 7, 8, 9
  (10 số) hay cố định 02 rồi 9 số, `+84` thay số 0, bỏ khoảng trắng, chấm, gạch, ngoặc; `tax_code_vn` là 10 số,
  10 số cộng `-` và 3 số chi nhánh, hay 12 số (mã cá nhân); chưa kiểm số kiểm tra. `date-time` tự kiểm (thư viện
  không có nếu thiếu gói phụ, đo trên 4.26.0); `check_profile` từ chối `format` ngoài danh sách đóng. Nếu sai
  thì: sửa hai regex ở `json_schema.py` và bảng ca của test.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): sàn gửi tin không có khóa (chỉ tới được nếu sổ mất luật khóa của
  bước phê duyệt) trả `blocked:no_idempotency_key` thay vì bỏ qua sàn như trước; mọi `resolve` khác truyền
  `tenant_id=None` (lớp nền tảng: agent dựng một lần, wf-lite compile và simulate, `definitions_for`). Sửa chuỗi
  `old` cũ của `compliance-pdpl/mutations/08.yaml` (CP8), `digital-worker/mutations/02.yaml` (DWK16),
  `tenant-config/mutations/03.yaml` (R5.1, R5.3, R5.6) và `wf-ai/mutations/02.yaml` (R6.9) theo mã mới. Nếu sai
  thì: các mutation đó báo "không áp được" ở lúc đóng đợt.
- 2026-11-02 (agent): resolved. Khác ticket: bốn dòng trên. Mã: `tools.py` (`ToolBehaviour`, `pydantic_behaviour`,
  `SchemaViolation`, `ToolRegistry` hai lớp trên `TenantOverlay`), `tool_schema.py` (`check_profile`,
  `json_schema_behaviour`), `tool_kinds.py`, `json_schema.py` (`tool_problems`, `TOOL_FORMATS`), `executor.py`
  (`TOOL_STEP_ORDER`, `ToolSteps`, `ToolCall`, `approval_required`, bước `step_*`, đuôi `_tail`),
  `wflite_host.build_tool_executor_steps`; middleware và wrapper chỉ hỏi `approval_required`. Test: 73 unit mới
  (`test_tool_steps.py` 25, `test_tool_schema.py` 22, `test_tool_kinds.py` 17, `test_tool_registry.py` 4,
  `test_approval_required.py` 5), 1 integration mới và 1 mở rộng ở `test_send_floor_executor_db.py`; unit
  `dw_agent_runtime` 813 xanh, `dw_platform` 216/217 (đỏ `test_retention_fragments` vì
  `configs/copy/audit_actions.d/runtime-hardening.yaml` thiếu `copy_id`, có từ `48a6f3f`, không của ticket này);
  integration của ticket: `test_send_floor_executor_db` 5, `test_executor_db` 2, `test_tool_claims` 18,
  `apps/worker` `test_wflite_runs_db` 17 xanh. `mutations/01.yaml` 29 mutation, đã viết, chưa chạy (`mutate.py` chạy
  lúc đóng đợt). `reviewing-feature-security` đã đọc: cách ly tenant (R2.1, test chéo công ty), phê duyệt (cổng
  executor test thẳng), nội dung không tin cậy (lỗi không mang giá trị), mặc định đóng (sổ bắt buộc, loại và sàn
  thiếu thì từ chối, binding không nói là ghi); vòng đời: mục công ty trong dict cả tiến trình chưa có bên gỡ (M3,
  ticket 03). Không migration, không route.
