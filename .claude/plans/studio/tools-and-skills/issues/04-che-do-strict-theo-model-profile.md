# 04 — Chế độ strict của args schema theo cờ năng lực của model profile

Status: ready-for-agent
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

- [ ] R4.4: profile khai `strict_tools` → `render_input_schema` dựng bản strict (so chuỗi bằng byte với chuỗi model giả
      nhận): thuộc tính tùy chọn `note` nằm trong `required` với kiểu `["string", "null"]`; model giả gọi với
      `note: null` → executor nhận đầu vào không có `note`, lời gọi chạy; object lồng `address.ward` tùy chọn cũng vào
      `required` với `null`; khóa bắt buộc `lead_id: null` →
      `validation_failed`; gỡ bước bỏ `null` → lời gọi `note: null` bị từ chối, test đỏ.
- [ ] R4.4: Bộ công cụ có `max_strict_tools + 1` công cụ trên profile `strict_tools` → mọi công cụ ở dạng thường;
      đúng `max_strict_tools` → mọi công cụ strict.
- [ ] R4.4: profile `strict_tools` → định nghĩa công cụ gửi model giả mang cờ strict; gỡ cờ hay gửi bản strict không cờ →
      test đỏ.
- [ ] R4.4: profile `strict_tools` không khai `numeric_bounds` → bản strict gửi model không có `minimum`; đầu vào `amount: -5` vẫn bị
      executor từ chối với `validation_failed`.
- [ ] R4.6: profile không khai `strict_tools` → `render_input_schema` trả đúng lược đồ gốc; đọc nhầm cờ thành luôn
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
