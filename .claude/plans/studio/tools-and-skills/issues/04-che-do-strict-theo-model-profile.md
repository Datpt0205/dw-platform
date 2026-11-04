# 04 — Chế độ strict của args schema theo cờ năng lực của model profile

Status: resolved
Blocked by: 02, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md
Area: studio
Yêu cầu: R4.4, R4.6

## Mục tiêu

Bộ lắp Studio của ticket 02 dựng args schema ở chế độ strict cho model profile khai cờ `strict_tools`, và ở dạng thường
cho profile không khai, đọc cả ba cờ năng lực mà model-connections/02 thêm và nêu tools-and-skills là bên đọc
(`strict_tools`, `max_strict_tools`, `numeric_bounds`), trong khi executor vẫn kiểm theo lược đồ gốc (spec R4.4, R4.6,
R1.1). Tách từ ticket 02 (dòng 4/11/2026 của spec), vì connections-and-vault/05 cần bộ lắp và bộ bọc mà không cần cờ.

## Việc cần làm

1. Chế độ strict là hai việc cùng lúc: định nghĩa công cụ gửi nhà cung cấp mang cờ strict (`bind_tools(..., strict=True)`
   của LangChain) và args schema ở dạng strict; không bao giờ cờ mà không dạng hay dạng mà không cờ.
   `render_input_schema(schema, profile) -> dict` ở `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/studio_tools.py`,
   mà bộ lắp của ticket 02 gọi thay cho dạng thường: profile khai `strict_tools` → dạng strict (mọi thuộc tính vào
   `required`, thuộc tính không bắt buộc ở lược đồ gốc nhận thêm kiểu `null`, hay thêm `null` vào `enum` khi thuộc tính
   chỉ có `enum`, `additionalProperties: false` ở mọi object, đệ quy vào object lồng và phần tử mảng);
   profile không khai → dạng thường, đúng lược đồ gốc; `numeric_bounds` của profile khai → giữ `minimum`, `maximum` của
   lược đồ gốc trong bản strict, không khai → bỏ chúng khỏi bản strict; từ khóa khác mà hồ sơ `dw.tool-schema/v1` cho
   (`maxLength`, `format`, `exclusiveMinimum`, `multipleOf`) không vào bản strict; bản thường giữ nguyên mọi từ khóa;
   executor vẫn kiểm mọi từ khóa của lược đồ gốc (R1.1).
2. `max_strict_tools` (profile không khai thì không trần): Bộ công cụ của lượt cho ra nhiều công cụ hơn số này → mọi công cụ của lượt dựng ở dạng thường,
   không một phần strict một phần thường, vì executor kiểm lược đồ gốc ở mọi lời gọi (R1.1).
3. Thân `call` của ticket 02, trước `executor.execute`: với công cụ dựng ở dạng strict, bỏ khóa có giá trị `null` mà lược
   đồ gốc không khai bắt buộc và không nhận `null`, để executor kiểm đúng lược đồ gốc (R1.1, R1.3); khóa bắt buộc mang
   `null` vẫn tới executor và bị `validation_failed`.

## Tiêu chí chấp nhận

- [x] R4.4: profile khai `strict_tools` → `render_input_schema` dựng bản strict (so chuỗi bằng byte với chuỗi model giả
      nhận): thuộc tính tùy chọn `note` nằm trong `required` với kiểu `["string", "null"]`; model giả gọi với
      `note: null` → executor nhận đầu vào không có `note`, lời gọi chạy; object lồng `address.ward` tùy chọn cũng vào
      `required` với `null`; khóa bắt buộc `lead_id: null` →
      `validation_failed`; gỡ bước bỏ `null` → lời gọi `note: null` bị từ chối, test đỏ.
- [x] R4.4: Bộ công cụ có `max_strict_tools + 1` công cụ trên profile `strict_tools` → mọi công cụ ở dạng thường;
      đúng `max_strict_tools` → mọi công cụ strict.
- [x] R4.4: profile `strict_tools` → định nghĩa công cụ gửi model giả mang cờ strict; gỡ cờ hay gửi bản strict không cờ →
      test đỏ.
- [x] R4.4: profile `strict_tools` không khai `numeric_bounds` → bản strict gửi model không có `minimum`; đầu vào `amount: -5` vẫn bị
      executor từ chối với `validation_failed`.
- [x] R4.6: profile không khai `strict_tools` → `render_input_schema` trả đúng lược đồ gốc; đọc nhầm cờ thành luôn
      strict → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- spec: R4.4, R4.6, R1.1, R1.3; model-connections/02 (cờ `strict_tools`, `max_strict_tools`, `numeric_bounds`,
  model-connections:R2.3); ticket 02 (bộ lắp, thân `call`).

## Comments

- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách từ ticket 02 ở gate của ticket đó (dòng 4/11/2026 của spec);
  hình bản strict và cách bỏ `null` là của gate (B2 của builder check). Nếu sai thì: bản strict giữ thuộc tính tùy chọn
  ngoài `required`, và bước 3 rút.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): `render_input_schema(schema, capabilities)` nhận `ModelCapabilities`
  của route mà model của agent gọi (cờ năng lực sống ở route, không ở hồ sơ); `studio_tools(...)` nhận
  `capabilities=` bắt buộc, agent-builder/03 truyền cờ của route `chat` đã ghim. Trần `max_strict_tools` là
  `turn_capabilities(capabilities, count)`, trả bản cờ tắt `strict_tools` khi quá trần, nên một chỗ quyết cả dạng lẫn cờ
  (`PinnedTools.strict`). Nếu sai thì: `studio_tools` nhận cả `ModelProfile` và tự chọn route.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): cờ strict tới nhà cung cấp qua `StrictToolsMiddleware` (đặt
  `model_settings["strict"]`, mà `create_agent` chuyển cho `bind_tools`), `platform_middleware` chỉ cài khi
  `pinned.strict`; đo trên langchain 1.4.1, langchain-openai 1.6.2. Nếu sai thì: bọc model bằng `bind_tools` riêng của
  Studio và `create_agent` nhận model đã bọc.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): `max_strict_tools` không khai là không trần, theo bước 2; chú thích
  ở `model/profiles.py` ("unset is no strict tools") sửa theo, vì đọc như cũ thì `strict_tools` của luna và gateway
  không ai đọc (failure-modes #1). Nếu sai thì: đảo điều kiện trong `turn_capabilities` và đổi test
  `test_an_unset_ceiling_is_no_ceiling`.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): bản strict giữ theo danh sách cho phép (`type`, `description`, `enum`,
  `const`, cùng `minimum`/`maximum` khi `numeric_bounds`), mọi từ khóa khác bị bỏ, nên một từ khóa mới của hồ sơ không
  lọt vào bản strict. Thuộc tính tùy chọn nhận `null` qua `type`, rồi `enum` (cả hai khi có cả hai; `const` thành
  `enum`), rồi một nhánh `anyOf`; đệ quy cả vào nhánh `anyOf`. Bước 3 (`drop_strict_nulls`) chạy đầu thân `call`, qua
  tham số `admit` của `tool_call`, trước câu hỏi phê duyệt và khóa chống lặp, theo lược đồ gốc
  (`behaviour.input_schema()`), qua object lồng, phần tử mảng và nhánh `anyOf`: bỏ `null` khi không nhánh nào khai khóa
  đó bắt buộc hay nhận `null`. Nếu sai thì: đổi `_STRICT_KEYWORDS` và `_dropped`.
- 2026-11-05 (agent): đo thật một lần (lời gọi `strict: true` ép công cụ, lược đồ của test) trên gateway: `gpt-5.6-luna`
  (Responses), `gpt-4o-mini`, `gpt-4.1` đều nhận bản strict (`["object", "null"]` lồng, `enum` có `null`, mảng object),
  gửi `null` cho mọi khóa tùy chọn; sau `drop_strict_nulls` đầu vào qua lược đồ gốc, 0 lỗi.
- 2026-11-05 (agent): MEDIUM, chưa sửa. (M1) Chưa cửa nào gọi `studio_tools` với cờ thật: agent-builder/03 truyền
  `capabilities` của route đã ghim. (M2) Route `fallback` của hồ sơ có thể không khai `strict_tools`; agent Studio W1
  không chuyển route giữa lượt, nhưng ticket nào thêm chuyển route thì dựng lại công cụ theo cờ của route mới. (M3) Gốc
  lược đồ có `description` thì LangChain thay bằng mô tả công cụ, nên bản model nhận khác bản render đúng khóa đó.
- 2026-11-05 (agent): resolved. Mã: `adapters/studio_tools.py` (`render_input_schema`, `turn_capabilities`,
  `drop_strict_nulls`, `StrictToolsMiddleware`, `PinnedTools.strict`), `adapters/langchain_tools.py` (`admit`),
  `adapters/agent_factory.py`, `adapters/chat_model.py` (`bound_kwargs`), chú thích `model/profiles.py`. Test:
  `test_strict_tool_schemas.py` 15 unit (so byte qua `ChatOpenAI.bind_tools` thật), `test_studio_tools.py` và
  `test_toolset_seal.py` (`_lane2`, 6) theo chữ ký mới; unit toàn repo 3277 xanh, phủ 76,67%. Bộ mới xanh ngay lần đầu,
  nên đã bẻ bằng tay cả 14 mutation của `mutations/04.yaml` trên bản sao gói: 14 đỏ; `mutate.py` chạy lại lúc đóng đợt.
  `reviewing-feature-security`: không bảng, cache, route hay ghi mới; executor vẫn kiểm lược đồ gốc (khóa bắt buộc
  `null`, `amount: -5` bị từ chối ở thân `call` thật); bước bỏ `null` chỉ bỏ, không thêm, và chỉ khóa mà lược đồ gốc từ
  chối; cờ không khai → dạng thường. Chờ lúc đóng đợt: `mutate.py`, `make test-integration` đầy đủ, latency lời gọi công
  cụ Studio (thêm một lượt duyệt lược đồ mỗi lời gọi strict), `/code-review`.
