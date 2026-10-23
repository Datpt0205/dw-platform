# Công cụ là dữ liệu của tenant, kỹ năng và bộ công cụ

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Trợ lý Marketing cần đọc lead và gửi email, mà mỗi lời gọi công cụ phải được kiểm theo đúng lược đồ và
chính sách của công ty, chạy với quyền của người hỏi, và không để kết quả từ bên ngoài đóng vai chỉ
dẫn. Spec này đưa mọi hiệu ứng công cụ — từ trợ lý hay từ bước quy trình — qua đúng một `ToolExecutor`
tự kiểm JSON Schema (LangChain không kiểm lược đồ dạng dict), áp Mức sàn theo loại mà công ty chỉ siết
được, và hỏi sàn gửi tin trước mỗi Hành động gửi tin. Công cụ là dữ liệu của công ty theo Loại công cụ,
tới model chỉ dưới dạng phiên bản đã ghim trong Bộ công cụ, với đầu ra bọc là dữ liệu từ bên ngoài. W1
ship executor, Bộ công cụ ghim và công cụ đọc đối tượng cho trợ lý; bảng công cụ do tenant viết, kỹ
năng và công cụ mã là W2 (ADR-0116 (Proposed), ADR-0111 (Proposed), ADR-0124 (Proposed)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `ToolExecutor` kiểm đầu vào (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:151`)
  và đầu ra (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:236`) bằng mô hình
  Pydantic, theo chuỗi ở docstring resolve → validate → authorize → execute → validate → audit
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:3`). Ràng buộc: giữ kiểm Pydantic
  cho công cụ định nghĩa bằng code (G1); Thiếu: không có đường kiểm JSON Schema dạng dict cho công cụ dữ
  liệu tenant.
- `jsonschema` không có trong khối phụ thuộc của `dw_agent_runtime`
  (`packages/python/dw_agent_runtime/pyproject.toml:15`). Thiếu: bộ kiểm JSON Schema của executor.
- `ToolSpec` là lớp nền tảng với `side_effect_level` và `approval_policy`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:36-50`); không có `simulate_safe`,
  phân loại dữ liệu hay độ tin cậy đầu ra, không ràng buộc theo Loại công cụ. Thiếu: công cụ chưa là dữ
  liệu tenant theo loại với Mức sàn theo loại.
- `ScopedToolsMiddleware` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:281`)
  và `OfferedToolsOnlyMiddleware`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:422`) lọc phần tử
  không phải `BaseTool`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:304`);
  `_ALWAYS_ALLOWED = {"write_todos"}`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:419`). Ràng buộc:
  đây là cổng công cụ hiện tới model, foundations-hardening/04 siết thêm.
- `StructuredTool` dựng ở
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:495`, chưa dùng
  `response_format` `content_and_artifact`. Thiếu: bọc đầu ra là dữ liệu từ bên ngoài và artifact.
- `deepagents>=0.7,<1` chưa ghim chính xác
  (`packages/python/dw_agent_runtime/pyproject.toml:18`). Ràng buộc: foundations-hardening/04 ghim
  `==0.7.15`; nâng lên `>=0.7.23` cho `SkillsMiddleware` là W2.

## Mục tiêu

### R1 — Executor tự kiểm JSON Schema đầu vào và đầu ra

Mỗi lời gọi công cụ dữ liệu tenant được kiểm theo lược đồ của công cụ, do executor tự kiểm vì LangChain
không kiểm lược đồ dạng dict (YC59; ADR-0116 (Proposed) quyết 3).

- R1.1 KHI model gọi một công cụ dữ liệu tenant, `ToolExecutor` PHẢI kiểm đầu vào theo JSON Schema
  Draft 2020-12 của Hợp đồng công cụ trước khi gọi handler, và từ chối với `validation_failed` nêu
  `path` khi sai.
- R1.2 KHI handler trả kết quả, `ToolExecutor` PHẢI kiểm đầu ra theo output JSON Schema của công cụ và
  từ chối với `tool_output_invalid`, không đưa đầu ra cho model, khi sai.
- R1.3 NẾU đầu vào có trường ngoài lược đồ (`additionalProperties` false), THÌ `ToolExecutor` PHẢI từ
  chối với `validation_failed` và không gọi handler.

### R2 — Công cụ là dữ liệu tenant theo loại, một cửa, mức sàn chỉ siết

Mọi hiệu ứng công cụ đi qua một cửa, phân giải theo công ty; một nhà máy theo Loại công cụ; và Mức sàn
theo loại mà công ty chỉ siết được (YC59, YC60, YC64; ADR-0116 (Proposed) quyết 1, 3).

- R2.1 KHI một công cụ được gọi, `ToolExecutor` PHẢI phân giải Đặc tả công cụ theo công ty của ngữ
  cảnh lượt chạy và chạy mọi hiệu ứng của mọi loại qua đúng một cửa.
- R2.2 KHI dựng một công cụ, một nhà máy theo Loại công cụ PHẢI trả Cách thực thi cho `object_crud` và
  `connector_action` ở W1, và cho `http`, `mcp`, `workflow`, `code` về sau.
- R2.3 NẾU Chính sách công cụ hạ Mức tác động hay chính sách duyệt xuống dưới Mức sàn theo loại của nó,
  THÌ việc xuất bản PHẢI trả 422 `kind_floor_violation` và không xuất bản.
- R2.4 Chính sách của công ty PHẢI chỉ siết thêm Mức sàn theo loại (trọng yếu, luôn duyệt, bộ ba nguy
  hiểm), không bao giờ hạ.
- R2.5 NẾU một lời gọi cần duyệt tới `ToolExecutor` với `approved` là false, THÌ `ToolExecutor` PHẢI
  trả `approval_required` và không gọi handler, kể cả khi người gọi bỏ qua wrapper.

### R3 — Sàn gửi tin kiểm ở executor

Trước mỗi Hành động gửi tin, executor hỏi sàn gửi tin, nên `tool.call` của quy trình, lời gọi công cụ
của agent và quy trình dùng như công cụ đều qua một kiểm (YC86; ADR-0124 (Proposed) quyết 2).

- R3.1 KHI một Hành động có `effect_class` là `message` sắp chạy, `ToolExecutor` PHẢI hỏi
  `SendAdmissionPort` ở mỗi lời gọi trước khi gọi handler, không nhớ kết quả giữa các lời gọi.
- R3.2 NẾU `SendAdmissionPort` trả từ chối (thiếu đồng ý đúng mục đích còn hiệu lực, đang bị chặn liên
  hệ, ngoài khung giờ gửi, hay vượt tần suất), THÌ `ToolExecutor` PHẢI không gọi nhà cung cấp và trả kết
  quả bị chặn kèm lý do.

### R4 — Bộ công cụ ghim thành StructuredTool

Model chỉ gọi được công cụ trong Bộ công cụ đã ghim của phiên bản agent, ghim theo id phiên bản và mã
băm nội dung (YC59; ADR-0116 (Proposed) quyết 5, 6).

- R4.1 Model PHẢI chỉ gọi được công cụ trong Bộ công cụ đã ghim của phiên bản agent.
- R4.2 KHI đưa một phiên bản công cụ đã ghim cho model, bộ lắp PHẢI dựng một `StructuredTool` có tên tối
  đa 64 ký tự với `response_format` là `content_and_artifact`.
- R4.3 NẾU tên công cụ dài hơn 64 ký tự (64 thì nhận, 65 thì không), THÌ bộ lắp PHẢI trả `ConfigError`
  và không đưa công cụ cho model.
- R4.4 ĐỐI VỚI model profile khai cờ năng lực `strict_tools`, bộ render lược đồ PHẢI dựng args schema ở
  chế độ strict.
- R4.5 NẾU một phiên bản agent ghim quá 40 công cụ, THÌ việc xuất bản PHẢI trả 422 `too_many_tools` và
  không ghim.
- R4.6 ĐỐI VỚI model profile không khai `strict_tools`, bộ render lược đồ PHẢI dựng args schema thường.

### R5 — Đầu ra công cụ là dữ liệu từ bên ngoài, cắt theo ngân sách

Mọi kết quả công cụ đưa cho model được bọc là dữ liệu từ bên ngoài và cắt, để nội dung lead không đóng
được khối và thành chỉ dẫn (YC48; ADR-0010 (Accepted); ADR-0116 (Proposed) quyết 5).

- R5.1 KHI đưa đầu ra công cụ cho model, bộ bọc PHẢI bọc nó là dữ liệu từ bên ngoài theo
  ADR-0010 (Accepted) và cắt ở `max_output_chars` (mặc định 8 000 ký tự), không bao giờ quá 16 KiB.
- R5.2 NẾU đầu ra chứa chuỗi đóng khối `</tool_output>` hay `<system>`, THÌ bộ bọc PHẢI escape nó để
  model nhận `&lt;/tool_output&gt;` và nội dung không thành chỉ dẫn.

### R6 — Công cụ dữ liệu đối tượng theo phiên bản lược đồ, dùng quyền người gọi

Trợ lý đọc được lead, chiến dịch và tương tác theo đúng quyền của người hỏi bằng công cụ đọc đối tượng,
không giữ công cụ gửi tin hay sửa bản ghi (YC19, YC23, YC96; ADR-0116 (Proposed) quyết 1).

- R6.1 KHI một phiên bản đối tượng được ghim vào Bộ công cụ, `ObjectToolGenerator` PHẢI sinh công cụ
  `obj.<api_name>.search` và `obj.<api_name>.get` (W1 chỉ đọc) từ bộ chiếu lược đồ của đối tượng theo
  `schema_version`.
- R6.2 KHI model gọi một công cụ dữ liệu đối tượng, công cụ PHẢI chạy qua RecordService với `AccessContext`
  của người kích hoạt hoặc tài khoản dịch vụ chạy dưới danh nghĩa, đánh giá lại ở từng lời gọi.
- R6.3 Lược đồ model thấy của một công cụ dữ liệu đối tượng PHẢI chỉ gồm trường người gọi đọc được, do
  `FieldSecurityToolSchemaMiddleware` thu hẹp.
- R6.4 NẾU trợ lý của công ty B gọi một công cụ dữ liệu đối tượng hỏi bản ghi của công ty A, THÌ công cụ
  PHẢI trả `not_found` và không lộ bản ghi.
- R6.5 NẾU một phiên bản đối tượng mới xóa một trường mà một công cụ đã ghim bản cũ còn dùng, THÌ công cụ
  ghim bản cũ PHẢI báo lệch.
- R6.6 Công cụ `obj.<api_name>.search` và `obj.<api_name>.get` PHẢI mang Mức tác động `none` và trả id
  bản ghi cùng chỉ trường người gọi đọc được.
- R6.7 NẾU một lời gọi công cụ dữ liệu đối tượng dùng một trường đã bị xóa ở phiên bản đối tượng mới, THÌ
  RecordService PHẢI từ chối lời gọi đó.

## Hành vi giữ nguyên

- G1 KHI một lượt chạy của worker định nghĩa bằng code gọi công cụ, `ToolExecutor` PHẢI TIẾP TỤC kiểm
  đầu vào và đầu ra bằng mô hình Pydantic của công cụ đó (test:
  `packages/python/dw_agent_runtime/tests/unit/test_executor.py::test_happy_path_returns_typed_output_and_audits`).
- G2 KHI một lượt chạy đang dở phát lại một lời gọi, `ToolExecutor` PHẢI TIẾP TỤC trả kết quả đã lưu
  theo khóa chống lặp mà không chạy lại handler (test:
  `packages/python/dw_agent_runtime/tests/unit/test_executor.py::test_replay_returns_cached_output_without_reexecution`).

## Trong phạm vi

- Mã: `tool_schema.py` (`check_profile` cho hồ sơ `dw.tool-schema/v1`, `JsonSchemaValidator` Draft
  2020-12 với `FormatChecker` danh sách đóng); `ToolRegistry.resolve(name, version, tenant_id)` trên
  chuỗi nguồn (lớp nền tảng cộng `TenantToolStorePort`); `ToolKindFactory` và bảng `kind -> factory` ở
  composition root; `KIND_FLOORS` và `check_policy_against_floor`; `approval_required` dùng chung bởi
  wrapper, `OneApprovalPerStepMiddleware` và executor; `SendAdmissionPort` tiêu thụ trong executor cho
  `effect_class: message`; `ToolsetSpec` (`dw.toolset/v1`); bộ lắp `StructuredTool` (`studio_tools.py`)
  và `contain_tool_output`; `ObjectDataPort`, `ObjectToolGenerator`, `FieldSecurityToolSchemaMiddleware`.
- Audit: `tool.simulated`, `tool.failed` (giữ tên hiện có), và bước kiểm sàn gửi tin ghi lý do bị chặn
  theo ADR-0124 (Proposed).
- Không tạo bảng mới: công cụ đọc đối tượng sinh từ phiên bản lược đồ; Bộ công cụ nhúng trong phiên bản
  agent; `platform.tool_executions` và `platform.tool_execution_claims` là của foundations-hardening/04.

## Ngoài phạm vi

| Việc                                                                                         | Vì sao                                                                                    | Chủ                                                              |
| -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| W2: bảng công cụ do tenant viết, phiên bản bất biến, xuất bản, API và màn quản trị           | `from_briefs` B8b 03, 09; W1 không có bảng công cụ do tenant viết                         | tools-and-skills đợt sau (W2)                                    |
| W2: công cụ `http` qua egress client; nhập OpenAPI                                           | YC66; `from_briefs` B8b 06, 13; cần `EgressClientPort` và màn quản trị công cụ            | tools-and-skills đợt sau (W2)                                    |
| W2: cờ nhiễm (`tainted_at`), điều kiện duyệt, người duyệt chỉ định                           | YC67; `from_briefs` B8b 07; cần CEL `ExpressionEngine` và tiền tố duyệt nghiêm            | tools-and-skills đợt sau (W2)                                    |
| W2: giới hạn và telemetry riêng của executor                                                 | `from_briefs` B8b 08; phần đóng băng ở agent-lifecycle/01, hạn mức ở usage-and-limits/04  | tools-and-skills đợt sau (W2); agent-lifecycle; usage-and-limits |
| W2: deepagents `>=0.7.23`; kỹ năng, màn Kỹ năng, nhập xuất `.zip`                            | YC66; `from_briefs` B8b 10, 11, 12; `SkillsMiddleware` cần deepagents mới                 | tools-and-skills đợt sau (W2)                                    |
| W2: quy trình làm công cụ; công cụ mã trong code-sandbox                                     | YC69; `from_briefs` B8b 14, 15; cần `WorkflowStartPort` và sandbox mỗi lượt               | tools-and-skills đợt sau (W2); workflow-engine; code-sandbox     |
| W2: chọn công cụ theo lượt; công cụ nền tảng chỉ siết; kiểm vùng ra theo tuyến               | `from_briefs` B8b 16, 17, 18; cần embedding mô tả và luật xuyên biên giới                 | tools-and-skills đợt sau (W2); compliance-pdpl                   |
| W3: tìm công cụ phía nhà cung cấp; script của kỹ năng trong sandbox                          | `from_briefs` B8b 19, 20                                                                  | tools-and-skills đợt sau (W3)                                    |
| Sổ đồng ý tiếp thị và `SendAdmissionPort` cài đặt; đồng ý bị rút hết hiệu lực trong ≤ 5 phút | ADR-0124 (Proposed); executor là một cửa, sổ đồng ý là của compliance-pdpl                | compliance-pdpl                                                  |
| Kho bí mật, egress client, Bản mô tả trình kết nối, Hành động `connector_action`             | ADR-0115 (Proposed), ADR-0116 (Proposed); spec này gọi qua port                           | connections-and-vault                                            |
| Vỏ phiên bản, chỉ mục phụ thuộc, bước niêm phong; chế độ chạy do máy chủ đặt                 | ADR-0109 (Proposed), ADR-0111 (Proposed); Bộ công cụ nhúng trong phiên bản agent          | tenant-config; agent-builder                                     |
| `ObjectSchemaProjector`, RecordService, bảng bản ghi; mô hình bảo mật trường                 | ADR-0107 (Proposed), ADR-0106 (Proposed); spec này gọi qua `ObjectDataPort` và middleware | custom-objects; field-security                                   |
| Máy chủ MCP, cổng MCP, ghim băm tool MCP                                                     | ADR-0116 (Proposed) quyết 7-8; dùng executor và egress ở đây                              | mcp-client                                                       |

## Kiểm soát

| #   | Kiểm soát                                               | Yêu cầu          | Test âm                                                                                                                                                                                  |
| --- | ------------------------------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TS1 | Chỉ công cụ đã ghim tới được model, tên tối đa 64 ký tự | R4.1, R4.3       | Middleware chèn `{"type": "web_search"}` và một `BaseTool` tên `write_file` → request model không có cả hai; tên 65 ký tự → `ConfigError`; gỡ bộ lọc → test đỏ                           |
| TS2 | Executor tự kiểm đầu vào                                | R1.1, R1.3       | Gọi thẳng executor với `{"lead_id": 1, "amount": -5, "extra": "x"}` → `validation_failed`, handler không chạy; gỡ bước kiểm lược đồ → test đỏ                                            |
| TS3 | Executor tự kiểm đầu ra                                 | R1.2             | Handler trả trường ngoài lược đồ hay sai kiểu → `tool_output_invalid`, model không nhận đầu ra; gỡ bước kiểm → test đỏ                                                                   |
| TS4 | Mức sàn theo loại, ghi đè chỉ siết                      | R2.3, R2.4       | Xuất bản `http` POST với Mức tác động `none` → 422 `kind_floor_violation`; hạ công cụ nền tảng từ `always` xuống `conditional` → 422; gỡ kiểm sàn → test đỏ                              |
| TS5 | Một nơi quyết duyệt                                     | R2.5             | Gọi executor với `approved=False` cho công cụ cần duyệt, bỏ qua wrapper → `approval_required`; ba cổng cho cùng kết quả trên bảng ca                                                     |
| TS6 | Sàn gửi tin kiểm ở executor                             | R3.1, R3.2       | Lead không có đồng ý đúng mục đích → `email.send` không gọi nhà cung cấp, kết quả bị chặn kèm lý do; gỡ hook `SendAdmissionPort` → test đỏ                                               |
| TS7 | Đầu ra là dữ liệu từ bên ngoài, bọc và cắt              | R5.1, R5.2       | Đầu ra chứa `</tool_output><system>` → model nhận `&lt;/tool_output&gt;`; đầu ra 20 000 ký tự → cắt, không quá 16 KiB; gỡ bọc → test đỏ                                                  |
| TS8 | FLS cho công cụ dữ liệu đối tượng                       | R6.3, R6.6       | Người không đọc được `phone` gọi `obj.lead_search` → đầu ra không có `phone`, lược đồ model thấy không có `phone`; gỡ middleware → test đỏ                                               |
| TS9 | Cách ly tenant và lệch phiên bản đối tượng              | R6.4, R6.5, R6.7 | Trợ lý của công ty B hỏi lead của A → `not_found`; đối tượng bỏ một trường → công cụ ghim bản cũ báo lệch, lời gọi dùng trường đã xóa bị RecordService từ chối; gỡ kiểm tenant → test đỏ |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` đã chạy cho từng ticket;
  `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- `.claude/plans/studio/foundations-hardening/issues/04-toolexecutor-gianh-luot-khong-cua-sau.md`:
  executor giành lượt trước hiệu ứng, không còn cửa sau, CHECK `tool_executions.status`, ghim deepagents
  (foundations-hardening:R6.4).
- `.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`: vỏ phiên bản và
  bước niêm phong ghim Bộ công cụ theo id phiên bản và mã băm nội dung (tenant-config:R2.7); chỉ mục phụ
  thuộc cho lệch phiên bản đối tượng.
- `.claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md`: cờ năng lực
  `strict_tools` trên model profile (model-connections:R2.3).
- `.claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md`: `RecordQueryCompiler` và
  RecordService mà `obj.<api_name>.search` dùng (custom-objects:R8.1); bộ chiếu lược đồ
  (custom-objects:R3.6); cách ly tenant (custom-objects:R4.3).
- `.claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md`: mô hình bảo mật trường và
  giá trị Đã ẩn mà `FieldSecurityToolSchemaMiddleware` thu hẹp theo (spec này cùng wave, xem ghi chú
  checker).
- `.claude/plans/studio/connections-and-vault/issues/05-manifest-va-ket-noi-email.md`: Hành động
  `connector_action` (gồm `email.send`) mà executor chạy qua một cửa (connections-and-vault:R6.1).
- Protocol do bên dùng khai: `SendAdmissionPort` (spec này khai, compliance-pdpl đáp ứng);
  `ObjectDataPort` (spec này khai, custom-objects đáp ứng); `TenantToolStorePort` (lớp tenant W2).
- Kiểm lại khi: DO-43 đổi model nào được cấp công cụ → R2; `ObjectSchemaProjector` đổi hình → R6, ticket
  03; `SendAdmissionPort` của compliance-pdpl đổi hình → R3, ticket 01; trần 32 000 ký tự của
  ADR-0116 (Proposed) vượt 16 KiB → R5.1 (xem Quyết định).

## Câu hỏi còn mở

- Q1. Ở v1, công ty chỉ đăng ký máy chủ MCP trong danh mục nền tảng hay cả URL tùy ý (DO-46)? Chủ: Đạt
  và người yêu cầu. Không đổi: W1 không có công cụ MCP; `ToolExecutor` và nhà máy theo loại không đổi,
  loại `mcp` do mcp-client thêm sau.

## Quyết định

- 22/10/2026 (người yêu cầu): S8: công cụ là dữ liệu của công ty theo loại; executor kiểm bằng
  jsonschema (LangChain không kiểm lược đồ dạng dict); chính sách công ty chỉ siết Mức sàn theo loại
  (ADR-0116 (Proposed) quyết 1, 3). Sửa: R1, R2.
- 23/10/2026 (agent, tạm): DO-43 theo khuyến nghị (a): công cụ cấp cho model BYOM của tenant; không
  fallback từ model của tenant sang model nền tảng trả phí; không endpoint on-premises ở v1. Sửa: R2.2.
  Nếu sai thì: giới hạn công cụ chỉ cho model nền tảng và đổi nhà máy loại.
- 23/10/2026 (agent, tạm): DO-45 theo khuyến nghị (a): Python 3.12, không JavaScript, không chạy script
  của kỹ năng ở v1; công cụ mã và kỹ năng là W2. Sửa: Ngoài phạm vi.
- 23/10/2026 (agent, tạm): DO-46 theo khuyến nghị (a): client MCP trước, chỉ máy chủ trong danh mục nền
  tảng ở v1; elicitation ở v1.5. Sửa: Ngoài phạm vi (mcp-client).
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: YC48 cắt kết quả công cụ ở 16 KiB, ADR-0116 (Proposed) và
  brief đặt trần 32 000 ký tự cho bản model nhìn thấy; theo YC48, đầu ra không bao giờ quá 16 KiB. Sửa:
  R5.1.
- 23/10/2026 (agent, tạm): khóa quyền `studio.tool.read`, `.author`, `.publish`, `.suspend` theo dạng
  của tenant-rbac/01. Sửa: mục Trong phạm vi. Nếu sai thì: đổi tên khóa theo danh mục tenant-rbac.
- 23/10/2026 (agent, tạm): `discovery/config-chang.md` cho thấy chang.fpt.net tách Skills, Credentials,
  Plugin và MCP thành các mục cấu hình riêng; Studio cố ý không có khái niệm "plugin" (Bỏ qua) — một
  "plugin" ứng với một Nhóm công cụ (namespace trong tên công cụ), không phải thực thể lưu trữ, vì công
  cụ là dữ liệu tenant theo Loại công cụ và Bộ công cụ có phiên bản (ADR-0116 (Proposed) quyết 1, 6).
  Nếu sai thì: thêm một loại thành phần gói nhiều công cụ dưới một tên.

## Danh sách ticket

| #   | Ticket                                                                                                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Executor tự kiểm JSON Schema, phân giải theo tenant, khe nhà máy theo loại](issues/01-executor-kiem-schema-va-nha-may.md) |
| 02  | [dw.toolset/v1 và công cụ ghim phiên bản thành StructuredTool, bọc và cắt đầu ra](issues/02-toolset-va-cong-cu-ghim.md)    |
| 03  | [Công cụ dữ liệu đối tượng theo phiên bản lược đồ, dùng quyền của người gọi](issues/03-cong-cu-du-lieu-doi-tuong.md)       |
