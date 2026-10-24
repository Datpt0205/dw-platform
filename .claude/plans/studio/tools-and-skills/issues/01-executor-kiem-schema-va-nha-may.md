# 01 — Executor tự kiểm JSON Schema, phân giải theo tenant, khe nhà máy theo loại

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/04-toolexecutor-gianh-luot-khong-cua-sau.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R3.1, R3.2, G1, G2, TS2, TS3, TS4, TS5, TS6, TS10

## Mục tiêu

Executor tự kiểm đầu vào và đầu ra bằng JSON Schema (LangChain không kiểm lược đồ dạng dict), phân giải
công cụ theo công ty, một nhà máy theo Loại công cụ với Mức sàn theo loại mà công ty chỉ siết, một nơi
quyết duyệt, một hook sàn gửi tin cho Hành động `effect_class: message`, và một thứ tự bước duy nhất cho
`ToolExecutor` (spec R1, R2, R3). Mọi loại công cụ Studio sau này thừa hưởng một cửa này. Gộp từ B8b-tools
tools-and-skills 02; đóng đường vòng quanh executor đã nằm ở foundations-hardening/04.

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
8. Thứ tự bước trong `ToolExecutor._execute` theo R2.6: công tắc điều khiển (agent-lifecycle/01 chèn),
   phân giải, kiểm đầu vào, kiểm quyền, chế độ chạy (tenant-config/03 chèn), phê duyệt, sàn gửi tin, giành
   lượt (foundations-hardening/04), gọi handler, kiểm đầu ra, audit; ghi thứ tự này ở docstring đầu
   `executor.py` thay chuỗi cũ. Ở chế độ khác `live`, lời gọi bị giả lập dừng ở bước chế độ chạy, nên không
   gọi `approval_required` và không mở phê duyệt (tenant-config:R5.6; ADR-0111 (Accepted) quyết 5).

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
      chạy, phê duyệt, sàn gửi tin) → spy của mọi bước sau không được gọi, handler không chạy; công cụ
      `critical` cần duyệt gọi ở `simulate` → lời gọi `simulated`, không `approval_required`, không dòng
      `platform.approval_requests` nào, còn ở `live` → `approval_required`; đảo hai bước liền nhau, kể cả
      chế độ chạy và phê duyệt → test đỏ.
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
- spec: R1, R2, R3, TS2-TS6; ADR-0116 (Accepted) quyết 3; ADR-0124 (Accepted) quyết 2;
  foundations-hardening/04 (`ToolClaimPort`, CHECK `tool_executions.status`); tenant-config/03 (bước chế
  độ chạy, tenant-config:R5.1).

## Comments

- 2026-10-23 (agent): brief ticket 01 (đóng đường vòng, ghim deepagents, test hợp đồng) đã gộp vào
  foundations-hardening/04; ticket này là brief ticket 02 cộng hook sàn gửi tin
  (YC86, ADR-0124 (Accepted)).
- 2026-10-23 (agent): thêm R2.6 (thứ tự bước một chủ) và Blocked by tenant-config/03 theo phát hiện kiểm
  nhất quán cùng ngày, vì cả hai ticket viết lại chuỗi bước của `ToolExecutor._execute`; audit từ chối của
  sàn gửi tin là `marketing.send_refused` của compliance-pdpl, `tool.simulated` là của tenant-config:R5.2.
  Theo DO-05 (Đạt, 23/10/2026), lượt chạy Studio chỉ dùng phiên bản đã ghim (bước 3).
- 2026-10-24 (agent): theo quyết định Đạt ngày 24/10/2026: N2 đặt bước chế độ chạy trước bước phê duyệt (bước 8;
  R2.6, TS10; hành vi giả lập không mở phê duyệt là tenant-config:R5.6); Mức sàn kiểm lúc lưu và lúc gửi kiểm
  định (bước 5, R2.3); thêm Blocked by agent-lifecycle/01, vì ticket đó chèn bước công tắc vào cùng chuỗi bước
  của `ToolExecutor._execute`.
