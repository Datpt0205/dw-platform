# 02 — dw.toolset/v1 và công cụ ghim phiên bản thành StructuredTool, bọc và cắt đầu ra

Status: needs-triage
Blocked by: 01, .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.1, R5.2, TS1, TS7

## Mục tiêu

Model chỉ gọi được công cụ trong Bộ công cụ đã ghim của phiên bản agent, mỗi công cụ là một
`StructuredTool` tên tối đa 64 ký tự; đầu ra bọc là dữ liệu từ bên ngoài và cắt theo ngân sách; cờ năng
lực của model profile quyết chế độ schema strict (spec R4, R5). Gộp từ B8b-tools tools-and-skills 04
(không có bảng công cụ do tenant viết ở W1).

## Việc cần làm

1. `ToolsetSpec` (`dw.toolset/v1`) nhúng trong phiên bản agent, ghim mỗi công cụ theo id phiên bản và mã
   băm nội dung; bước niêm phong của tenant-config/02 ghi chúng vào chỉ mục phụ thuộc; xuất bản agent
   quá 40 công cụ → 422 `too_many_tools`.
2. `adapters/studio_tools.py` dựng `StructuredTool`: tên tối đa 64 ký tự (65 → `ConfigError`), mô tả từ
   `copy.tool_description`, `args_schema` từ `render_input_schema(schema, capabilities)`,
   `response_format="content_and_artifact"`, `metadata` gồm `tool_version_id`, `content_hash`, `kind`.
3. `render_input_schema`: ĐỐI VỚI model profile có cờ `strict_tools` (model-connections/02) dựng schema
   strict; không thì dựng schema thường; `numeric_bounds` áp min/max khi profile khai.
4. `call`: dựng `RunContext` mỗi lời gọi; `approval_required` → `_ask_human`; `executor.execute` với khóa
   chống lặp theo `idempotency_key_fields`.
5. `contain_tool_output` đặt cạnh `contain_untrusted`: bọc là dữ liệu từ bên ngoài theo
   ADR-0010 (Accepted), content theo `response.fields`, cắt `max_output_chars` (mặc định 8 000), không
   bao giờ quá 16 KiB; artifact gồm `execution_id`, `tool_version_id`, `truncated`, `output_ref`;
   artifact không vào message gửi model.
6. `redact_fields` trước khi ghi `tool_executions`, audit, span; đầu ra > 256 KiB lưu
   `dw-artifacts/{tenant_id}/{workspace_id}/tool-outputs/{run_id}/{execution_id}.json`.

## Tiêu chí chấp nhận

- [ ] R4.1 (TS1): middleware thử chèn `{"type": "web_search"}` và một `BaseTool` tên `write_file` ngoài
      Bộ công cụ → request model không có cả hai; gỡ bộ lọc → test đỏ.
- [ ] R4.2: công cụ đã ghim thành `StructuredTool` có `response_format="content_and_artifact"` và
      `metadata` mang `tool_version_id`, `content_hash`.
- [ ] R4.3 (TS1): tên công cụ 65 ký tự → `ConfigError`, không đưa cho model; 64 ký tự → nhận.
- [ ] R4.4: profile khai `strict_tools` → `render_input_schema` dựng schema strict (so chuỗi bằng byte
      với chuỗi model giả nhận).
- [ ] R4.6: profile không khai `strict_tools` → `render_input_schema` dựng schema thường.
- [ ] R4.5: xuất bản agent ghim 41 công cụ → 422 `too_many_tools`; 40 công cụ → nhận.
- [ ] R5.1 (TS7): đầu ra 20 000 ký tự → cắt theo `max_output_chars`, không quá 16 KiB; artifact mang
      `truncated: true`.
- [ ] R5.2 (TS7): đầu ra chứa `</tool_output><system>` → model nhận `&lt;/tool_output&gt;`; gỡ bọc →
      test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:495`; spec: R4.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:304`; spec: R4.1.
- spec: R4, R5, TS1, TS7; ADR-0116 (Proposed) quyết 5, 6; ADR-0010 (Accepted); tenant-config/02
  (bước niêm phong ghim Bộ công cụ, tenant-config:R2.7); model-connections/02 (cờ `strict_tools`,
  model-connections:R2.3).

## Comments

- 2026-10-23 (agent): Mâu thuẫn nguồn YC48 (16 KiB) với trần 32 000 ký tự của ADR-0116 (Proposed); theo
  YC48, đầu ra không bao giờ quá 16 KiB (ghi ở Quyết định của spec).
