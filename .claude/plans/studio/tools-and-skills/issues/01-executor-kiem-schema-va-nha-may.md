# 01 — Executor tự kiểm JSON Schema, phân giải theo tenant, khe nhà máy theo loại

Status: needs-triage
Blocked by: .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R3.1, R3.2, G1, G2, TS2, TS3, TS4, TS5, TS6, TS10, TS12, TS13

## Mục tiêu

Executor tự kiểm đầu vào và đầu ra bằng JSON Schema (LangChain không kiểm lược đồ dạng dict), phân giải
công cụ theo công ty, một nhà máy theo Loại công cụ với Mức sàn theo loại mà công ty chỉ siết, một nơi
quyết duyệt, một hook sàn gửi tin cho Hành động `effect_class: message`, và một sổ bước có thứ tự cho
`ToolExecutor` ở composition root, nơi mỗi ticket chủ đăng ký bước của mình (spec R1, R2, R3; H-3). Mọi loại công cụ
Studio sau này thừa hưởng một cửa này. Gộp từ B8b-tools tools-and-skills 02; đóng đường vòng quanh executor đã nằm ở
runtime-hardening/01.

## Việc cần làm

1. `jsonschema==4.26.0` thành phụ thuộc trực tiếp của `dw_agent_runtime`; module
   `dw_agent_runtime/tool_schema.py`: `check_profile(schema)` (hồ sơ `dw.tool-schema/v1`),
   `JsonSchemaValidator` (Draft 2020-12, `FormatChecker` danh sách đóng có `phone_vn`, `tax_code_vn`,
   `referencing.Registry()` rỗng, `additionalProperties: false` bắt buộc), lỗi trả `path`, không trả giá
   trị.
2. `ToolBehaviour(validate_input, validate_output, handler, approval_preview)`: bản Pydantic cho công cụ
   định nghĩa bằng code (giữ G1), bản JSON Schema cho công cụ dữ liệu tenant.
3. `ToolRegistry.resolve(name, version, *, tenant_id)` theo công ty, không bao giờ trả công cụ của công ty
   khác; `ToolExecutor` resolve bằng `run_context.tenant_id`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:146`); lượt chạy Studio chỉ dùng
   phiên bản công cụ đã ghim trong bản kê lượt chạy, không rơi về lớp nào lúc chạy (DO-05; bộ lắp của
   ticket 02 truyền phiên bản ghim).
4. `ToolKindFactory.build(binding, contract, deps) -> ToolBehaviour`, một bảng `kind -> factory` ở
   composition root, một bộ lắp duy nhất tạo `RegisteredTool`; W1 có `object_crud` và `connector_action`.
5. `KIND_FLOORS` và `check_policy_against_floor(policy, floor)` dùng cho Mức sàn theo loại và ghi đè; chỉ
   siết, không hạ; một hàm này trả 422 `kind_floor_violation` lúc lưu và lúc gửi kiểm định (niêm phong), theo
   ADR-0116 (Accepted) quyết 1.
6. `ToolExecutor.approval_required(definition, run_context, args, step_calls)` dùng chung bởi wrapper,
   `OneApprovalPerStepMiddleware` và executor; đặt bước kiểm quyền duyệt tại executor
   (`.../executor.py:135`).
7. `SendAdmissionPort` khai ở đây, tiêu thụ trong `ToolExecutor` cho mọi Hành động `effect_class:
message` (compliance-pdpl cài); từ chối → không gọi handler, trả kết quả bị chặn kèm lý do. Audit của
   lần từ chối là `marketing.send_refused` do compliance-pdpl ghi trong giao dịch của executor
   (compliance-pdpl:R3.1); ticket này không ghi audit thứ hai.
8. Sổ bước của `ToolExecutor` (R2.6, R2.7; H-3): một hàm duy nhất ở composition root,
   `build_tool_executor_steps(deps)`, mà API (`apps/api/src/dw_api/bootstrap/wiring.py`) và worker
   (`apps/worker/src/dw_worker/main.py`) cùng gọi, khai các bước theo đúng thứ tự R2.6: công tắc điều khiển, phân
   giải, kiểm đầu vào, kiểm quyền, chế độ chạy, phê duyệt, sàn gửi tin, giành lượt, ghi `dispatched`, gọi handler, kiểm
   đầu ra, audit. Ticket này đưa vào sổ các bước của nó, bước chế độ chạy của tenant-config/03 và bước giành lượt và
   ghi `dispatched` của runtime-hardening/01 (hai ticket đi trước, viết trong `_execute` hiện có); danh sách bước chờ
   đăng ký của sổ ghi công tắc điều khiển (agent-lifecycle/01) và sàn gửi tin (`MarketingSendPolicy` của
   compliance-pdpl/04), mỗi mục nêu đường dẫn ticket chủ. `ToolExecutor._execute` chỉ chạy các bước của sổ theo thứ
   tự đó, không gọi bước nào ngoài sổ; đăng ký một tên ngoài R2.6, hay một tên hai lần, là `ConfigError` lúc khởi động;
   ghi thứ tự ở docstring đầu `executor.py` thay chuỗi cũ. Test sổ: so tên các bước với dãy R2.6 và đỏ, nêu bước, khi
   hai bước ngược thứ tự, có tên lạ, hay vắng một bước không có trong danh sách chờ. Ở chế độ khác `live`, lời gọi bị
   giả lập dừng ở bước chế độ chạy, nên không gọi `approval_required` và không mở phê duyệt (tenant-config:R5.6;
   ADR-0111 (Accepted) quyết 5).
9. Bước sàn gửi tin khi còn chờ đăng ký (R2.8): mọi lời gọi tới Hành động `effect_class: message` trả kết quả bị chặn
   `blocked:send_floor_unavailable`, không gọi handler; khi compliance-pdpl/04 đăng ký `MarketingSendPolicy`, bước đó
   hỏi `SendAdmissionPort` như bước 7.

## Tiêu chí chấp nhận

- [ ] R1.1 (TS2): gọi thẳng executor với `{"lead_id": 1, "amount": -5, "extra": "x"}` cho công cụ dữ
      liệu tenant → `validation_failed` nêu `path`, handler (spy) không chạy; gỡ bước kiểm lược đồ → test
      đỏ.
- [ ] R1.2 (TS3): handler trả trường ngoài lược đồ hay sai kiểu → `tool_output_invalid`, model không
      nhận đầu ra; gỡ bước kiểm đầu ra → test đỏ.
- [ ] R1.3 (TS2): đầu vào có trường ngoài lược đồ → `validation_failed`, handler không chạy.
- [ ] R2.1: executor resolve Đặc tả công cụ bằng `run_context.tenant_id`; công cụ của công ty khác →
      `not_found`.
- [ ] R2.2: nhà máy theo loại trả Cách thực thi cho `object_crud` và `connector_action`; bảng
      `kind -> factory` ở composition root.
- [ ] R2.3 (TS4): lưu và gửi kiểm định `http` POST với Mức tác động `none` → 422 `kind_floor_violation`, không
      lưu, không niêm phong; gỡ kiểm sàn → test đỏ.
- [ ] R2.4 (TS4): hạ công cụ nền tảng từ `always` xuống `conditional` qua ghi đè công ty → 422; siết từ
      `conditional` lên `always` → nhận.
- [ ] R2.5 (TS5): gọi executor với `approved=False` cho công cụ cần duyệt, bỏ qua wrapper →
      `approval_required`, handler không chạy; ba cổng (wrapper, middleware, executor) cho cùng kết quả
      trên bảng ca.
- [ ] R2.6 (TS10): bảng ca gọi thẳng executor, mỗi ca từ chối ở một bước (phân giải, đầu vào, quyền, chế độ
      chạy, phê duyệt, sàn gửi tin, giành lượt) → spy của mọi bước sau không được gọi, không dòng `dispatched` nào,
      handler không chạy; lời gọi qua mọi bước → dòng `dispatched` có trước lời gọi handler; công cụ
      `critical` cần duyệt gọi ở `simulate` → lời gọi `simulated`, không `approval_required`, không dòng
      `platform.approval_requests` nào, còn ở `live` → `approval_required`; đảo hai bước liền nhau, kể cả
      chế độ chạy và phê duyệt → test đỏ.
- [ ] R2.7 (TS12): sổ thử đảo bước chế độ chạy và bước phê duyệt, thêm một bước không có tên trong R2.6, hay bỏ bước
      phân giải mà không đưa vào danh sách chờ → test sổ đỏ, nêu bước; sổ của API và của worker cùng dựng từ
      `build_tool_executor_steps`, và gỡ một dòng đăng ký của hàm đó → test đỏ; `_execute` gọi một bước ngoài sổ → test
      đỏ; sổ thật của ticket này với hai bước chờ đăng ký → xanh.
- [ ] R2.8 (TS13): bước sàn gửi tin còn chờ đăng ký, gọi `email.send` (`effect_class: message`) →
      `blocked:send_floor_unavailable`, handler (spy) không chạy; một Hành động khác `message` → chạy như thường; cho
      bước chờ đăng ký đi qua → test đỏ.
- [ ] R3.1 (TS6): Hành động `effect_class: message` → executor hỏi `SendAdmissionPort` trước mỗi lời gọi
      (spy thấy một lần mỗi lời gọi).
- [ ] R3.2 (TS6): lead không có đồng ý đúng mục đích → `email.send` không gọi nhà cung cấp, kết quả bị
      chặn kèm lý do, và executor không tự ghi audit nào cho lần từ chối; gỡ hook `SendAdmissionPort` →
      test đỏ.
- [ ] G1: `test_happy_path_returns_typed_output_and_audits` và mọi test executor hiện có xanh.
- [ ] G2: `test_replay_returns_cached_output_without_reexecution` xanh (phát lại theo khóa chống lặp
      không chạy lại handler).
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:151`; spec: R1.1, G1.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:236`; spec: R1.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:135`; spec: R2.5.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:3`; spec: R2.6 (chuỗi bước cũ ở
  docstring).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:36-50`; spec: R2.3, R2.4.
- spec: R1, R2, R3, TS2-TS6, TS12, TS13; H-3; ADR-0116 (Accepted) quyết 3; ADR-0124 (Accepted) quyết 2;
  runtime-hardening/01 (`ToolClaimPort`, CHECK `tool_executions.status`, dòng `dispatched`, runtime-hardening:R6.11);
  tenant-config/03 (bước chế độ chạy, tenant-config:R5.1).

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
