# 01 — Tài liệu `dw.workflow/v1` của gói, sổ sáu loại bước, bộ kiểm và luật sàn HITL

Status: needs-triage
Blocked by: .claude/plans/studio/digital-worker/issues/02-hang-doi-ban-giao-cong-duyet.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R4.1, R4.2, R4.3, WFL1, WFL2, WFL3, WFL4, WFL5, WFL6, WFL7, WFL8, WFL19, WFL20, WFL24

## Mục tiêu

Nền tảng đọc, kiểm và ghim tài liệu quy trình của gói trước khi nhận việc nào, và không tài liệu
nào để một hiệu ứng ra ngoài xảy ra ngoài lane "Duyệt" của cổng của loại quyết định của nó (R1-R4, D16).

## Việc cần làm

1. `dw_agent_runtime/wflite/document.py`: mô hình Pydantic `extra="forbid"` của tài liệu (`schema`,
   `key`, `version` semver, `triggers[]`, `steps[]` cây, `variables[]` `{name, type: string | integer |
number | boolean | uuid, default?, required}`, `decision_classes[]` `{key, effect_level, reversible,
ceiling}`, `work_kinds[]` `{kind, schema}`), bước `{id, type, config, description?}`.
2. `dw_agent_runtime/wflite/registry.py`: `NodeTypeSpec` và `build_node_registry()` với đúng sáu
   loại của R2.1; schema config: `trigger.work_item@1` `{kind}`; `ai.llm@1` `{prompt, inputs,
output_schema, min_confidence?}`; `tool.call@1` `{tool, input, decision_class}`;
   `human.approval@1` `{decision_class, proposal, locked_fields?}` với lane `approved`, `rejected`;
   `time.wait@1` `{seconds | seconds_param}`; `logic.switch@1` `{on, cases: {<giá trị>: [bước]},
default: [bước]}`.
3. `dw_agent_runtime/wflite/validate.py`: một hàm trả mọi lỗi `[{path, code, message_vi,
message_en}]` với mã `wf.schema_invalid`, `wf.duplicate_step_id`, `wf.unknown_type`,
   `wf.config_invalid`, `wf.ref_not_dominating`, `wf.router_not_total`, `wf.tool_unknown`,
   `wf.decision_class_undeclared`, `wf.hitl_gate_missing`, `wf.effect_above_class`,
   `wf.unapproved_input`, `wf.param_undeclared`, `wf.ref_unknown`; tham chiếu `{{ steps.<id>.<trường> }}`,
   `{{ work.<trường> }}`, `{{ params.<tên> }}`, mỗi tham chiếu là cả một giá trị chuỗi (R3.7); "đứng
   trước trên mọi đường" tính trên cây (bước trước trong cùng danh sách, hay bước trước khối chứa
   lane); "nằm trong lane `approved`" của R4.1 là bước thuộc danh sách của lane đó hay của một khối lồng
   trong nó.
4. `dw_agent_runtime/wflite/catalog.py`: `PackCatalog.load(root)` đọc `configs/packs/*/workflows/*.yaml`
   và `schemas/*.json`, sha256 mỗi tệp, kiểm bằng bước 3 với `ToolSpecRegistry`; lỗi thì ném
   `ConfigError` nêu tệp và mã; cấp `WorkKindSchemas` của digital-worker/02.
5. Nạp `PackCatalog` ở composition root của API và worker (fail fast, R3.5); một tài liệu mẫu tối thiểu
   dưới `packages/python/dw_agent_runtime/tests/fixtures/packs/` cho test (gói Marketing thật là
   leadcare/01).
6. Test âm WFL1-WFL8, WFL19, WFL20, mỗi mã lỗi một ca đỏ và một ca hợp lệ.

## Tiêu chí chấp nhận

- [ ] R1.1: tài liệu mẫu nạp được với sha256 đúng của tệp.
- [ ] R1.2 (WFL1): khóa lạ, thiếu `steps`, tên tệp `a@1.0.0` với `version: 1.0.1` → `wf.schema_invalid`, không nạp.
- [ ] R1.3: hai bước cùng `id` → `wf.duplicate_step_id`; `id` `Score` → `wf.schema_invalid`.
- [ ] R1.4: `WorkKindSchemas` trả schema của kind khai; kind không khai → không có schema.
- [ ] R2.1: sổ có đúng sáu loại, không hơn.
- [ ] R2.2 (WFL2): `http.request@1` → `wf.unknown_type`; `ai.llm@1` thiếu `prompt` → `wf.config_invalid`.
- [ ] R3.1: tài liệu có ba lỗi khác nhau trả đủ ba trong một lần gọi.
- [ ] R3.2 (WFL3): tham chiếu tới bước trong lane khác của switch → `wf.ref_not_dominating`; tới bước trước switch → hợp lệ.
- [ ] R3.2 (WFL24): `{{ steps.draft.khong_co }}` → `wf.ref_unknown`.
- [ ] R3.3 (WFL4): switch không `default` → `wf.router_not_total`.
- [ ] R3.4 (WFL5): công cụ không có spec → `wf.tool_unknown`; loại không khai → `wf.decision_class_undeclared`.
- [ ] R3.5 (WFL6): thêm tệp lỗi vào thư mục gói tạm → dựng ứng dụng API và worker ném `ConfigError` nêu tệp.
- [ ] R3.6 (WFL20): `{{ params.khong_co }}` → `wf.param_undeclared`; `{{ work.khong_co }}` → `wf.ref_unknown`.
- [ ] R3.7 (WFL20): `"Chào {{ work.name }}"` → `wf.config_invalid`.
- [ ] R3.8 (WFL20): `min_confidence` với `output_schema` không có `confidence` → `wf.config_invalid`.
- [ ] R4.1 (WFL7): `tool.call` công cụ `external` không cổng, cổng ở lane khác, sau khối duyệt, và trong lane `rejected` → `wf.hitl_gate_missing`; trong lane `approved` của cổng cùng loại → hợp lệ.
- [ ] R4.3 (WFL19): `input` của `tool.call` có cổng là `{{ steps.draft.subject }}`, hay một đối tượng ghép → `wf.unapproved_input`; `input` là `{{ steps.approve_send.proposal }}` → hợp lệ.
- [ ] R4.2 (WFL8): công cụ `external` dưới loại `internal` → `wf.effect_above_class`.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `docs/adr/0112-workflows-compile-to-langgraph-one-effect-per-node.md:47-116`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:110`; spec: R1-R4, WFL1-WFL8, WFL19, WFL20.

## Comments

- 2026-10-29 (agent): viết lại theo gate `checking-plan-readiness` lượt 1.
