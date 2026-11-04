# 02 — dw.toolset/v1 và công cụ ghim phiên bản thành StructuredTool, bọc và cắt đầu ra

Status: resolved (2026-11-04, main)
Blocked by: 01, .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.5, R5.1, R5.2, R5.3, TS1, TS7

## Mục tiêu

Model của một agent Studio chỉ gọi được công cụ trong Bộ công cụ nhúng trong phiên bản agent, mỗi công cụ là một
`StructuredTool` tên tối đa 64 ký tự dựng từ đúng bản mà bản kê lượt chạy ghim; đầu ra bọc là dữ liệu từ bên ngoài và
cắt theo ngân sách ở một nơi (spec R4.1-R4.3, R4.5, R5; YC48). Chế độ strict theo cờ năng lực của model profile
(R4.4, R4.6) là ticket 04. Gộp từ B8b-tools tools-and-skills 04 (không có bảng công cụ do tenant viết ở W1).

## Việc cần làm

1. `dw.toolset/v1` (spec, dòng 4/11/2026 về hình; ADR-0116 (Accepted) quyết 6): `ToolsetSpec` (`extra="forbid"`) ở
   `packages/python/dw_studio/src/dw_studio/tools/domain/toolset.py`, là mục `toolset` nhúng trong tài liệu `dw.agent/v1`
   của agent-builder/02, không là một loại thành phần: `{tools: [...]}`, mỗi mục một trong hai loại W1,
   `{kind: object_crud, object: <id thành phần đối tượng>, operations: [search, get]}` (`operations` không rỗng, chỉ
   `search`, `get` ở W1) hay `{kind: connector_action, connector: "<key>@<semver>", action: <tên Hành động>, binding: <tên điểm gắn>}`, tên công
   cụ là tên mà connections-and-vault/05 biên dịch cho Hành động đó. Hai hàm
   thuần cạnh nó:
    - `validate_toolset(spec) -> list[DocumentProblem]` trả mọi lỗi cùng lúc, mỗi lỗi con trỏ dưới `/toolset`: loại ngoài
      hai loại W1 → `toolset.kind_unsupported`; hai mục cho ra cùng một tên công cụ → `toolset.duplicate_tool`; tên Hành
      động mà `model_facing_name` (`langchain_tools.py:111`) cho ra dài hơn 64 ký tự → `tool_name_too_long`; tổng công cụ
      tới model, mỗi mục đối tượng tính một công cụ cho mỗi thao tác bật, lớn hơn 40 → `too_many_tools` (40 thì nhận).
      Tên công cụ đối tượng không cần kiểm: `API_NAME` (`packages/python/dw_studio/src/dw_studio/core/domain/artifacts.py:25`)
      giữ nó tối đa 52 ký tự.
    - `extract_toolset(spec) -> list[Reference]`: mục đối tượng → `artifact`, `to_key` là id thành phần, `usage` `read`;
      mục Hành động → `connector`, `to_key` là `connector` của mục, `usage` `invoke`, cộng `binding`,
      `to_key` là tên điểm gắn, `usage` `bind`; `path` là con trỏ của mục. Bước niêm phong của tenant-config/02 ghim phiên
      bản `live` và mã băm của mỗi đối tượng (`closure_of`, `packages/python/dw_studio/src/dw_studio/core/application/service.py:587`),
      nên tài liệu không mang id phiên bản.
      Validator và extractor của loại `agent` (agent-builder/02) gọi hai hàm này, không bản sao. Test của ticket này chứng
      minh R4.5 qua bước niêm phong bằng một loại fixture nhúng mục `toolset`, đưa vào app chỉ qua `kinds=` (tenant-config:R2.15).
2. Bộ lắp Studio `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/studio_tools.py`:
   `studio_tools(toolset, resolver, assembler, executor, ...) -> list[StructuredTool]` nhận mục `toolset` của tài liệu
   agent đã ghim, `PinnedResolver` của lượt (`packages/python/dw_agent_runtime/src/dw_agent_runtime/pinned.py:42`) và
   `ToolAssembler` của ticket 01 (`tool_kinds.py`, bảng `kind -> factory`); mỗi mục phân giải qua `resolver.resolve`, không
   bao giờ qua `ToolRegistry` hay lớp nền tảng lúc chạy (DO-05), rồi `assembler` dựng `RegisteredTool`. Một mục không
   dựng được (`key_not_pinned`, tên quá 64 ký tự, loại không có nhà máy) làm cả bộ lắp ném `ConfigError` và lượt kết thúc
   lỗi, không bao giờ chạy tiếp thiếu một công cụ (đóng khi thiếu). Mỗi `StructuredTool`:
   tên `model_facing_name(...)`, tối đa 64 ký tự (65 → `ConfigError`, công cụ không tới model; R4.3), mô tả là
   `ToolDefinition.description`, `args_schema` từ `ToolBehaviour` ở dạng thường, `response_format="content_and_artifact"`,
   `metadata` gồm `tool_version_id` (id phiên bản đối tượng đã ghim, hay khóa `<key>@<semver>` của manifest), `content_hash`
   (của mục ghim trong bản kê) và `kind`. Nhà máy thật là của ticket 03 (`object_crud`) và connections-and-vault/05
   (`connector_action`); test ở đây dùng nhà máy giả.
3. Một thân lời gọi: bộ lắp Studio dùng chung thân `call` của `_build_tool`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:495`), tách sao cho nhận bản ghim và
   bộ định dạng đầu ra: `RunContext` của lượt, `executor.approval_required` → `_ask_human`, khóa chống lặp của
   `_idempotency_key` (`langchain_tools.py:606`, băm đối số), rồi `executor.execute(..., pinned=registered)`. Không
   `idempotency_key_fields`, không `copy.tool_description`.
4. `ToolExecutor.execute(..., pinned: RegisteredTool | None = None)`: có `pinned` thì `step_resolve`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:485`) dùng đúng nó và không đọc `ToolRegistry`;
   tên hay phiên bản của nó khác lời gọi → `ConfigError`. Không ghi mục công ty nào vào `ToolRegistry`. Không `pinned` thì
   như hôm nay (worker định nghĩa bằng code, wf-lite).
5. Tới model chỉ các công cụ ghim (R4.1): agent Studio dựng `OfferedToolsOnlyMiddleware` với đúng các định nghĩa ghim và
   không tập luôn cho phép, nên `write_todos` (`_ALWAYS_ALLOWED`, `langchain_tools.py:419`) chỉ còn cho worker định nghĩa
   bằng code; `ScopedToolsMiddleware` vẫn bỏ mục không phải `BaseTool` (runtime-hardening/01).
6. `contain_tool_output(output, definition, execution_id)` cạnh `contain_untrusted`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`), dùng cùng một hàm escape: chiếu theo
   `response.fields` (JSON Pointer; rỗng là cả đầu ra), escape một lần theo ADR-0010 (Accepted), cắt ở
   `response.max_output_chars` ký tự và 16 384 byte UTF-8, cả hai đo trên nội dung đã escape, ở ranh giới ký tự và không
   giữa một thực thể như `&lt;`, rồi bọc `<tool_output source="<tên công cụ>" trust="untrusted">`; artifact
   `{execution_id, tool_version_id, truncated}` không vào message gửi model (R5.1-R5.3). Đây là nơi duy nhất bọc và cắt
   cho mọi công cụ bộ lắp Studio dựng, với đầu ra thành công và mẫu giả lập của chế độ khác `live`; lời từ chối
   (`validation_failed`, `approval_required`, `blocked:<lý do>`, `outcome_unknown`) tới model qua
   `PlatformToolErrorsMiddleware` như hôm nay, là chữ của nền tảng không mang đầu ra công cụ. Đầu ra chuyển thành chuỗi bằng
   `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`; nhiều `response.fields` cho ra một object khóa theo
   pointer; nội dung bị cắt kết thúc bằng dấu `[đã cắt]`, tính trong trần. Handler của mọi loại, kể cả `ManifestActionHandler` của connections-and-vault/05,
   trả kết quả thô. Đầu ra đầy đủ vẫn ở `platform.tool_executions.output`; `output_ref`, `redact_fields` và kho trên
   256 KiB là W2 (Ngoài phạm vi của spec). `response.fields` (danh sách JSON Pointer hợp lệ) và `response.max_output_chars`
   (số nguyên 1 tới 16 384, mặc định 8 000) vào `ToolSpec` (`tool_specs.py`) và `ToolDefinition` (`contracts.py`) cùng bên
   đọc này (ADR-0116 (Accepted) quyết 1).

## Tiêu chí chấp nhận

- [x] R4.1 (TS1): agent Studio ghim `obj_lead__search`; middleware thử chèn `{"type": "web_search"}`, một `BaseTool` tên
      `write_file` và `write_todos` → request model chỉ có `obj_lead__search` (hôm nay `write_todos` lọt qua); worker định
      nghĩa bằng code vẫn có `write_todos`; gỡ bộ lọc → test đỏ.
- [x] R4.1: lượt Studio gọi một công cụ cùng tên và phiên bản với một mục `ToolRegistry` nền tảng mà hành vi khác → chạy
      đúng hành vi của bản ghim; `pinned` mang tên khác lời gọi → `ConfigError`, handler không chạy; `step_resolve` đọc sổ
      khi có `pinned` → test đỏ.
- [x] R4.2: mục ghim thành `StructuredTool` có `response_format="content_and_artifact"` và `metadata` mang
      `tool_version_id`, `content_hash`, `kind` của mục trong bản kê; mục không có trong bản kê → `ConfigError`
      `key_not_pinned`, không công cụ nào được dựng.
- [x] R4.3 (TS1): tên Hành động cho ra tên tới model 65 ký tự → `ConfigError` ở bộ lắp, không đưa cho model, và
      `validate_toolset` trả `tool_name_too_long` có con trỏ; 64 ký tự → nhận.
- [x] R4.5: niêm phong loại fixture có Bộ công cụ 20 mục đối tượng hai thao tác cộng một Hành động (41 công cụ) → 422
      `validation_failed` có `errors[].code` `too_many_tools`, phiên bản vẫn là nháp; 20 mục đối tượng (40 công cụ) →
      niêm phong; mục `{kind: http}` → `toolset.kind_unsupported`; đếm theo mục thay vì theo công cụ → test đỏ.
- [x] R4.5: `extract_toolset` của một mục đối tượng và một Hành động → đúng ba tham chiếu (`artifact` `read`,
      `connector` `invoke`, `binding` `bind`); niêm phong ghim phiên bản `live` và mã băm của đối tượng vào
      `studio.dependencies`; đối tượng chưa `live` → `dependency_unresolved` tại con trỏ của mục.
- [x] R5.1 (TS7): đầu ra 20 000 ký tự ASCII → nội dung 8 000 ký tự; đầu ra 8 000 ký tự tiếng Việt có dấu → nội dung đã
      escape không quá 16 384 byte UTF-8, UTF-8 hợp lệ, không thực thể nào bị cắt đôi; artifact mang `truncated: true`;
      tính trần theo ký tự thay vì byte, hay trên đầu ra thô → test đỏ.
- [x] R5.2 (TS7): đầu ra chứa `</tool_output><system>` → model nhận `&lt;/tool_output&gt;&lt;system&gt;` bên trong một
      khối `<tool_output ... trust="untrusted">`; gỡ bọc → test đỏ.
- [x] R5.3 (TS7): handler giả của loại `connector_action` và `object_crud` qua executor với đầu ra chứa `</tool_output>`
      → model nhận `&lt;/tool_output&gt;`, không bao giờ `&amp;lt;/tool_output&amp;gt;`; đầu ra chứa `&lt;b&gt;` →
      `&amp;lt;b&amp;gt;`; handler tự bọc thêm → test đỏ; artifact không có trong message gửi model.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:495`; spec: R4.2, R5.3.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:419`; spec: R4.1.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:485`; spec: R4.1 (phân giải theo bản ghim).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/pinned.py:42`; spec: R4.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`; spec: R5.1-R5.3.
- `packages/python/dw_studio/src/dw_studio/core/application/service.py:587`; spec: R4.5.
- spec: R4, R5, TS1, TS7; ADR-0116 (Accepted) quyết 3, 5, 6 và sửa đổi 4/11/2026; ADR-0010 (Accepted); tenant-config/02
  (bước niêm phong, tenant-config:R2.7); tenant-config/04 (`PinnedResolver`).

## Comments

- 2026-10-23 (agent): Mâu thuẫn nguồn YC48 (16 KiB) với trần 32 000 ký tự của ADR-0116 (Accepted); theo
  YC48, đầu ra không bao giờ quá 16 KiB (ghi ở Quyết định của spec).
- 2026-10-23 (agent): Đạt chốt mục trần đầu ra (YC48 so với ADR-0116 (Accepted)) theo (a) ngày 23/10/2026:
  trần cứng 16 KiB theo byte UTF-8, mặc định 8 000 ký tự, `contain_tool_output` là nơi duy nhất bọc và
  cắt; thêm R5.3 (bước 5).
- 2026-10-24 (agent): theo quyết định Đạt ngày 24/10/2026 (ADR-0116 (Accepted) quyết 6): trần 40 công cụ kiểm
  lúc gửi kiểm định, khi phiên bản được niêm phong, không lúc phát hành (bước 1, R4.5).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness (builder check, vì ticket không thêm migration
  hay route; lượt xác nhận ngữ cảnh mới sau các sửa): 0 CRITICAL, 15 HIGH đã sửa theo khuyến nghị (dòng 4/11/2026 của
  spec). Lượt đầu: hình `dw.toolset/v1` nhúng trong tài liệu agent, không loại `toolset` (agent-builder/02, /05 sửa theo
  và chờ ticket này); trần 40 đếm công cụ tới model; tên Hành động kiểm lúc niêm phong; trần đo trên nội dung đã escape;
  một lần escape của ADR-0010 (Accepted); bọc chỉ công cụ của bộ lắp Studio; trường của bộ bọc trên `ToolSpec`, khóa
  chống lặp sẵn có; bước 6 cũ (kho trên 256 KiB, `redact_fields`) sang W2; không `write_todos` cho agent Studio; phân
  giải theo bản ghim qua `pinned=`; chế độ strict tách thành ticket 04. Lượt xác nhận: mục Hành động mang
  `connector` và `action`; mục không dựng được làm cả lượt lỗi; R4.4 nêu `max_strict_tools`; cờ strict, từ khóa, trần
  vắng và đệ quy ở ticket 04. Nếu sai thì: như `Nếu sai thì:` của các dòng 4/11/2026 trong spec.
- 2026-11-04 (agent): MEDIUM của gate, chưa sửa: (M1) eval `prompt_injection` cho đầu ra công cụ đi cùng bộ eval của
  ticket 03, công cụ thật đầu tiên tới model (CLAUDE.md, Observability and evaluation); ticket này chưa đưa công cụ thật
  nào tới model. (M2) `_idempotency_key` băm đối số trong một lượt, nên hai lời gọi gửi giống hệt nhau trong cùng lượt
  là một lần gửi (hành vi hôm nay, G2); lời gọi đọc mức `none` không có khóa. (M3) Một Hành động chỉ ghim được một lần
  mỗi Bộ công cụ (`toolset.duplicate_tool`), nên hai hộp thư SMTP cho cùng `email.send` cần hai agent ở W1. (M4)
  `platform.secret_subject_column` và mọi tên công cụ Hành động là của connections-and-vault/05; ticket này chỉ đọc tên
  biên dịch. (M5) Ticket không thêm migration hay route; lời gọi công cụ đo latency cùng đợt ở lúc đóng hàng.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `ToolsetSpec`, `validate_toolset`, `extract_toolset`, `parse_toolset`
  ở `packages/python/dw_studio/src/dw_studio/core/domain/toolset.py`, không ở `dw_studio/tools/domain`: loại `agent`
  (agent-builder/02), bộ sinh công cụ đối tượng (ticket 03) và bộ biên dịch Hành động (connections-and-vault/05) cùng
  đọc mục này, mà các năng lực của Studio không import nhau (studio-skeleton R5.2), và một năng lực `tools` mới cần sửa
  hợp đồng độc lập trong `pyproject.toml` mà lane khác đang sửa. Trần 64 ký tự, 40 công cụ và `model_facing_name` là
  của `dw_agent_runtime.contracts`, bước niêm phong và bộ lắp đọc cùng một số. Nếu sai thì: chuyển tệp sang
  `dw_studio.tools.domain`, thêm `dw_studio.tools` vào hợp đồng độc lập, và loại `agent` nhận hai hàm qua mục registry ở
  composition root.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `studio_tools(toolset, resolver, assembler, sources, executor, ...)`
  trả `PinnedTools(tools, definitions)` thay vì `list[StructuredTool]`, và `AgentSpec.pinned` là danh sách duy nhất mà
  công cụ và mọi middleware của agent Studio dựng từ đó (`offered` phải rỗng, `sub_agents` bị từ chối ở W1). Mỗi loại
  có một `PinnedToolSource` (`kind -> source`, cạnh `kind -> factory` của `ToolAssembler`) biên dịch mục và bản ghim
  thành `ToolBinding` cộng `ToolContract`: ticket 03 và connections-and-vault/05 cài nó. Mục là `ToolsetEntry`
  (Protocol `kind`, `pin()`), mục của `dw_studio` thỏa nó mà runtime không import Studio. `ToolAssembler.build` dựng
  không đăng ký; `assemble` = `build` rồi đăng ký. Bộ lắp cũng từ chối tên quá 64 ký tự và quá 40 công cụ (lớp thứ hai,
  mỗi lớp một test). Nếu sai thì: `studio_tools` trả `list[StructuredTool]` và định nghĩa đi kèm theo đường khác.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt Studio nhận dạng bằng `RunContext.run_manifest_hash` (cột
  `platform.worker_runs.run_manifest_hash` đã có): `step_resolve` dùng đúng `pinned`, từ chối `pinned` khác tên hay
  phiên bản (`pinned_mismatch`), và từ chối lời gọi không `pinned` của lượt có bản kê (`tool_not_pinned`) mà không đọc
  sổ. Trường vắng thì như hôm nay. Cửa nhận lượt Studio (agent-builder/03) đặt trường này và `run_store` mang nó khi
  tiếp tục; tới lúc đó lời gọi thiếu bản ghim của lượt Studio rơi về sổ (M6). Nếu sai thì: dấu lượt Studio là
  `RunContext.artifact` của agent-builder/03 và `step_resolve` đọc nó.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `ToolExecutor.execute_recorded(...)` trả `ToolResult(output,
execution_id)` (dòng thành công, dòng `simulated`, hay dòng thành công trước mà lần phát lại trả), `execute` giữ kiểu
  trả cũ cho mọi bên gọi; thân lời gọi chung `tool_call` ở `langchain_tools.py` (bước 3). `contain_tool_output(output,
definition, execution_id, *, tool_version_id)`: một con trỏ cho ra giá trị của nó (vắng là `null`), nhiều con trỏ
  cho ra object khóa theo con trỏ (chỉ con trỏ có giá trị); dấu `[đã cắt]` nối liền; tên `source` phải khớp
  `[A-Za-z0-9_-]{1,64}`. `ToolResponse` (`fields`, `max_output_chars`) là kiểu chung của `ToolSpec.response` và
  `ToolDefinition.response`. Nếu sai thì: đổi `_projected` và bảng ca của `test_tool_output_containment.py`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tiêu chí R4.1 "worker định nghĩa bằng code vẫn có `write_todos`" không
  còn đúng: runtime-hardening/01 gỡ `_ALWAYS_ALLOWED` ngày 30/10/2026 (`create_agent` không cài công cụ nào), nên không
  worker nào được `write_todos`; test của ticket này chứng minh agent Studio không nhận nó.
  Nếu sai thì: không có; tiêu chí viết trước khi gỡ.
- 2026-11-04 (agent): MEDIUM, chưa sửa. (M6) `run_manifest_hash` mở khi thiếu tới khi agent-builder/03 đặt nó ở cửa
  nhận lượt và `run_store` mang nó khi tiếp tục. (M7) Mẫu tên Hành động, khóa trình kết nối và tên điểm gắn trong
  `toolset.py` chép luật của connections-and-vault/05 và tenant-config/05; ticket nào dựng mẫu đó trong mã thì đọc
  một chỗ. (M8) Niêm phong không kiểm đích của mục `object_crud` là loại `object`; nguồn `object_crud` của ticket 03
  phải từ chối bản ghim không phải `dw.object/v1`. (M9) Hàm đổi lỗi pydantic thành `DocumentProblem` là bản thứ hai
  cạnh `records/domain/document.py`; gom vào `core.domain.artifacts` khi tệp đó không còn bị sửa song song.
- 2026-11-04 (agent): resolved. Mã: `contracts.py` (`ToolResponse`, `model_facing_name`, trần, `run_manifest_hash`),
  `executor.py` (`pinned`, `execute_recorded`, `ToolResult`), `tool_kinds.py` (`build`), `tool_specs.py`, `prompts.py`
  (`escape_untrusted`, `contain_tool_output`), `adapters/studio_tools.py`, `adapters/langchain_tools.py` (`tool_call`),
  `adapters/agent_factory.py` (`pinned`), `core/domain/toolset.py`, `testing/fixture_kinds.py` (fixture nhúng
  `toolset`). Test: `test_studio_tools.py` 17, `test_tool_output_containment.py` 24, `test_toolset.py` 12 unit,
  `test_toolset_seal.py` 6 integration (`_lane2`); unit `dw_agent_runtime` và `dw_studio` 1044 xanh. Bộ mới xanh ngay
  lần đầu, nên đã bẻ bằng tay cả 27 mutation của `mutations/02.yaml` trên bản sao gói (không sửa cây làm việc): 27 đỏ;
  `mutate.py` chạy lại lúc đóng đợt. `reviewing-feature-security` đã đọc: cách ly (đối tượng công ty khác như id không
  tồn tại, mục không ghim → `key_not_pinned`), quyền (executor tự từ chối bản ghim lệch và lời gọi không ghim),
  nội dung không tin cậy (một lần escape, cắt trên nội dung đã escape; eval tiêm là của ticket 03, M1), mặc định
  đóng (thiếu nguồn, nhà máy, bản ghim → cả bộ lỗi), vòng đời (không ghi vào sổ tiến trình). Không migration, route
  hay màn hình. Chờ lúc đóng đợt: `mutate.py`, `make test-integration` đầy đủ, latency của lời gọi công cụ (M5).
