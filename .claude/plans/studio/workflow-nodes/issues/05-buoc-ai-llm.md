# 05 — ai.llm: đầu ra có cấu trúc kiểm phía server, prompt bao chứa, tôn trọng opt-out

Status: ready-for-agent
Blocked by: 03, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md, .claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.4, R7.5, WN2, WN3

## Mục tiêu

Bước `ai.llm` trả đầu ra theo JSON Schema người dựng đặt, kiểm ở máy chủ, sửa tối đa một lần, với giá
trị bản ghi và `Mô tả cho AI` của đối tượng và trường chỉ vào prompt qua khối bao chứa (workflow-nodes R7.1, R7.2,
R7.4, R7.5, WN2, WN3). Bỏ qua bản ghi opt-out (R7.3, WN14) ở W2 cùng cờ của compliance-pdpl.

## Việc cần làm

1. **`ai.llm@2` của Studio, không sửa `ai.llm@1` của wf-lite** (ticket 02 bước 1; dòng Quyết định 4/11/2026 của spec).
    - `ai.llm@1` của wf-lite nêu một prompt nền tảng theo id (`name@semver`) và phân giải nó qua sổ prompt; Bước của
      Studio mang hướng dẫn và mẫu do công ty viết. Hai hợp đồng cấu hình khác nhau, nên Studio đăng ký `ai.llm@2` trong
      `studio_node_types` của ticket 03, và gói giữ nguyên `@1`.
    - `STUDIO_RULES.refused_types` (ticket 03) thêm `ai.llm@1`, nên đường Studio từ chối nó bằng
      `wf.unknown_type`, vì một lượt Studio chỉ phân giải từ bản kê, không qua sổ prompt lúc chạy (CLAUDE.md, Per-tenant
      artifacts). Danh mục `GET /api/v1/studio/node-types` của ticket 02 bỏ loại mà `STUDIO_RULES` từ chối.
    - `ai.llm@2` khai `block` `none`, `ends_run` và `exits_loop` sai, `side_effect_level` `none`, Khi lỗi `fail`,
      `continue`, `route`, và `opens_wait` sai nếu trường đã có. `dependencies(config)` trả một dòng `artifact` cho mỗi
      đối tượng của `context` (`usage` `read`) và một dòng nền tảng cho khung `studio/llm_node@1.0.0`, để bản kê ghim
      khung và Nơi đang dùng thấy đối tượng (ADR-0109 (Accepted) quyết 4, 5).
    - Đầu ra (R1.5): `response` là kết quả đã kiểm (đối tượng theo schema, hay `string` khi `output` là `text`) và
      `metadata` là `{tokens_in, tokens_out, cost, route_class}`, `cost` là chuỗi thập phân; Bước sau đọc
      `steps.x.response.score`.
    - Model: ở W1 là model mặc định mà bộ phân giải theo tenant của model-connections/02 chọn, kết nối của nó ghim trong
      bản kê (ADR-0109 (Accepted) quyết 6); cấu hình không có khóa chọn model, và hai Bước khác model là W2.
2. **Cấu hình**, hai trường văn bản tách nhau:
    - `instructions`: hướng dẫn của công ty, văn bản không có `{{ }}`, lint bằng đúng linter của agent-builder/02 (chặn
      `<input`, `<tenant_instructions`, `{{`), không linter thứ hai. Vào system message qua `assemble_system_prompt` của
      agent-builder/02, là một khối bao chứa riêng (ADR-0117 (Accepted) quyết 4).
    - `prompt`: Chuỗi có biến, `x-dw-sink` `prompt` (ticket 02 bước 5): chữ tĩnh tối đa 8 KiB, không tự viết `<input`
      (`prompt_literal_input_tag`), mỗi giá trị bao trong `<input name="v<n>">` và cắt ở 16 KiB. Vào user message.
    - `context`: danh sách tùy chọn `{object, fields[]}` (`api_name`). Với mỗi mục, Bước đưa `Mô tả cho AI`
      (`ai_description`, tối đa 500 ký tự, custom-objects/02) của đối tượng và của từng trường vào user message, mỗi
      nhãn một khối `<input name="ctx<n>">` thoát, cắt 16 KiB, như dữ liệu từ ngoài (R7.5, YC101). Giá trị bản ghi không
      vào qua `context`, chỉ qua `prompt`. Mô tả đọc từ phiên bản định nghĩa đối tượng mà bản kê ghim qua phụ thuộc của
      Bước. Lúc gửi kiểm định, đối tượng hay trường không có → `wf.config_invalid`, trường người gửi không đọc được →
      `field_not_readable`; lúc chạy, trường chủ thể chạy không đọc được → `field_hidden` (ticket 03 bước 2).
    - `output`: `text`, hay một JSON Schema của công ty. Lúc gửi kiểm định schema phải giữ hồ sơ `dw.tool-schema/v1`
      (`check_profile` của `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_schema.py`: gốc là object, mọi
      object đóng `additionalProperties: false`, sâu tối đa 5), và dạng JSON của nó tối đa 32 KiB (ADR-0112 (Accepted)
      quyết 8), không thì `wf.config_invalid`. "`additionalProperties: false` forced" của ADR đọc là "hồ sơ đòi", như
      `check_profile` làm: schema thiếu nó bị từ chối, không bị chèn thêm. Schema tới model như tham số đầu ra có cấu trúc
      của lời gọi qua `ModelGateway`, không nằm trong chữ của prompt; chữ trong schema (`description`, `title`, `enum`) là
      chỉ dẫn của công ty, lint như `instructions`.
    - Lỗi lint của `instructions` và lỗi mẫu của `prompt` là lỗi của bộ kiểm khi gửi kiểm định: lưu nháp trả chúng thành
      cảnh báo, niêm phong trả 422, như mọi lỗi `wf.*` (ADR-0112 (Accepted) quyết 3).
3. **Khung prompt** `configs/prompts/studio/llm_node@1.0.0.yaml`, dựng bằng `assemble_system_prompt`. Một lượt Studio
   phân giải khung này từ bản kê lượt chạy qua `PinnedResolver` và `RunManifestPort` đã dựng (`ece5697`), kể cả khi
   tiếp tục, không qua `TenantOverlay` lúc chạy (CLAUDE.md, Non-negotiable architecture; ADR-0109 (Accepted)).
4. **Lời gọi model**: bộ phân giải model theo tenant của model-connections/02 chọn model và đi qua `ResidencyGate`
   (CLAUDE.md). Ở `simulate` lời gọi model chạy thật, dưới hạn mức của người thử (ADR-0111 (Accepted) quyết 3), trừ ca
   kịch bản của Cổng chất lượng ghim kết quả cho Bước, mà wrapper áp thay lời gọi (H-18; workflow-engine:R4.27), nên
   Cổng chất lượng tất định.
   Metadata của Bước: token, chi phí và route class là của mục sổ sử dụng mà lời gọi ghi (`PricingPort` và sổ của
   usage-and-limits/02, `522bd4e`), Bước chép lại, không tự tính.
5. **Kiểm đầu ra phía server** (R7.1): đầu ra theo schema được kiểm bằng bộ kiểm JSON Schema của nền tảng (`jsonschema`
   ghim chính xác, CLAUDE.md mục Required stack; ADR-0116 (Accepted)), không thêm thư viện nào. Sai thì gửi lại một lần
   để sửa, trong cùng một lần thử: lời gọi sửa mang đường dẫn và từ khóa của mỗi lỗi kiểm, và đầu ra sai trước đó trong
   một khối `<input name="previous_output">` thoát, không bao giờ chữ lỗi của thư viện. Vẫn sai → `output_invalid`, một
   lỗi không thử lại được: wrapper không chạy lại lần thử vì nó (ADR-0112 (Accepted) quyết 5). Lời gọi hết giờ hay nhà
   cung cấp lỗi tạm là kết quả có kiểu mà wrapper thử lại theo `retry`; `ResidencyGate` từ chối hay hết trần chi tiêu
   là lỗi không thử lại; các mã đó là của bộ phân giải model và cổng cư trú, Bước không thêm mã, chỉ thêm nhãn tiếng
   Việt của `output_invalid` vào `configs/copy/run_reason_codes.d/workflow-nodes.yaml` (H-21). Với Khi lỗi `continue`,
   kênh của Bước là
   `{status: "error", error}`, Bước kế tiếp đọc `error` và không có đầu ra nào khác; với `route`, làn lỗi chạy; cả hai
   không dừng lượt (YC47). Token và chi phí của lần sửa cộng vào metadata của Bước.
6. **Bỏ qua bản ghi opt-out** (R7.3) là W2, cùng cờ của compliance-pdpl; ADR-0112 (Accepted) quyết 8 ghi pha đó ở
   Amendments 2026-11-04.
7. **Hình chiếu chấm điểm lead** (R7.4): quy trình chấm điểm không tham chiếu họ tên, số điện thoại, email hay Zalo id
   trong `prompt`, và đưa văn bản tự do qua `text.mask_contacts`. Đây là cấu hình của quy trình. Ticket này thử nó trên
   một tài liệu fixture của Bước chấm điểm trong test của mình; tài liệu thật của gói thí điểm là của marketing-pilot và
   phải qua cùng test. Một luật chung của Bước theo `pd_category` là W2 (Nếu sai thì của dòng Quyết định 4/11/2026).
8. **Eval** (CLAUDE.md, Observability and evaluation): bộ `evals/datasets/studio_llm_node_v1.jsonl` với ba nhóm ca:
   tiêm chỉ dẫn qua lời nhắn lead và qua `ai_description`, dữ liệu của công ty khác (một ca mà mẫu của tenant A không
   bao giờ thấy bản ghi của tenant B, vì giá trị chỉ đến từ môi trường của lượt), và thiếu bằng chứng (lead thiếu trường
   → `output_invalid` hay giá trị rỗng theo schema, không bịa). Grader khóa `studio.llm_node.<gate>` ở
   `dw_studio.testing`, đăng ký ở seam của `scripts/run_evals.py`.
9. **`effect_door`** (workflow-engine/03; bảng ở mục Trong phạm vi của spec, chủ duy nhất): `ai.llm@2` khai `model`; thiếu trường thì sổ từ chối đăng ký, và `incident` của `allowed_on_error` do luật của workflow-engine/07 suy từ trường này, loại không tự khai.

## Tiêu chí chấp nhận

- [ ] R7.1 (WN3): model giả trả `score=150` (ngoài lược đồ) hai lần → `output_invalid` ở `error`; với Khi lỗi `route`
      làn lỗi chạy, với `continue` Bước kế tiếp chạy và đọc `steps.x.error.code`; lượt chạy không dừng ở cả hai; model
      gọi đúng hai lần, wrapper không thử lại; gỡ kiểm JSON Schema → test đỏ.
- [ ] R7.1: model giả trả `score=150` rồi `score=80` → Bước thành công, `steps.x.response.score` là 80, không `error`;
      lời gọi sửa mang `previous_output` trong khối bao chứa; token của cả hai lần cộng vào `metadata`.
- [ ] R7.1: schema đầu ra thiếu `additionalProperties: false`, sâu 6 hay quá 32 KiB → `wf.config_invalid` lúc gửi kiểm
      định; `context` nêu một trường không có → `wf.config_invalid`.
- [ ] R7.2 (WN2): một lời nhắn lead chứa `</input>` vào prompt không đóng được khối; gỡ bao chứa → đỏ.
- [ ] R7.4: tài liệu mẫu của quy trình chấm điểm: đầu vào gửi model không chứa họ tên, số điện thoại, email hay Zalo id;
      số và email trong văn bản tự do hiện dạng đã che.
- [ ] R7.1: `instructions` chứa `<input` → lỗi của linter agent-builder/02, cảnh báo khi lưu nháp và 422 khi niêm phong;
      mô-đun bước không có hàm kiểm chuỗi `<input` nào của riêng nó (test kiến trúc).
- [ ] R7.5 (WN2): `ai_description` của trường `notes` chứa `</input>` và một chỉ dẫn → chỉ xuất hiện trong khối
      `<input>` đã thoát của mục bối cảnh, không đóng được khối; gỡ bao chứa ở mục bối cảnh → test đỏ.
- [ ] R7.1: tài liệu Studio dùng `ai.llm@1` → `wf.unknown_type`, không niêm phong; gói `lead_care@1.0.0` với `ai.llm@1`
      vẫn nạp; danh mục không trả `ai.llm@1`.
- [ ] R7.2: một lượt `live` tiếp tục sau khi khung `llm_node` có phiên bản mới → vẫn dùng khung mà bản kê ghim; cho Bước
      đọc khung qua sổ prompt → test đỏ.
- [ ] R7.2: `make eval-smoke` chạy bộ `studio_llm_node_v1` với model giả, grader tất định, xanh; gỡ bao chứa → ca tiêm
      chỉ dẫn đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_ai_llm_node.py && make eval-smoke` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`; spec: R7.2.
- ADR-0112 (Accepted) quyết 8; spec: R7.1.
- ADR-0010 (Accepted); spec: R7.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_schema.py:64` (`check_profile`); spec: R7.1 (hồ sơ
  schema đầu ra).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py:73` (`ai.llm@1` của wf-lite); spec: R7.1.
- ADR-0111 (Accepted) quyết 3; ADR-0112 (Accepted), Amendments 2026-11-04; spec: R7.3 (W2), Quyết định 4/11/2026.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026 (Q9): cờ Hạn chế xử lý ở W2, nên R7.3 và WN14 rời ticket này sang W2.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: ticket dùng `assemble_system_prompt` và linter của agent-builder/02, chờ ticket đó (A:agent-builder:R2.2~workflow-nodes/05); `Mô tả cho AI` vào prompt như dữ liệu từ bên ngoài (N3, YC101), chờ custom-objects/02 nơi trường này ra đời.
- 2026-10-24 (agent): theo V4.24 và V4.26 của Đạt: `continue` và `route` là hai Khi lỗi khác nhau của cây Bước, `continue` đi tiếp Bước kế tiếp còn `route` chạy làn lỗi, nên bước 2 và tiêu chí R7.1 thôi ghép "`continue` ... và đi Nhánh ra lỗi" và thử cả hai. Không thêm cạnh.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check; không route, không
  migration). Lượt đầu: 2 CRITICAL, 11 HIGH, đều sửa ở ticket này, spec (Quyết định 4/11/2026) và ADR-0112 (Accepted)
  Amendments 2026-11-04:
    - CRITICAL: bộ kiểm `jsonschema-rs` trái CLAUDE.md mục Required stack (`jsonschema`); nay là bộ kiểm của nền tảng.
    - CRITICAL: ADR-0112 (Accepted) quyết 8 bắt kiểm `ai_opt_out` mà spec dời R7.3 sang W2 theo Q9 (a) của Đạt; ADR nay
      ghi pha đó.
    - `ai.llm@1` của wf-lite (prompt nền tảng theo id) khác hẳn Bước của Studio: nay `ai.llm@2`, `STUDIO_RULES` từ chối
      `@1`.
    - Hướng dẫn của công ty và mẫu `{{ }}` là một hay hai trường, vào message nào: nay hai trường.
    - `Mô tả cho AI` lấy từ đâu, nằm ở khối nào: nay khóa `context`.
    - Che định danh là luật của Bước hay của quy trình chấm điểm: nay của quy trình, luật chung ở W2.
    - `default_output` không ai định nghĩa: bỏ, `continue` ghi `{status: "error", error}`.
    - `output_invalid` có qua `retry` của wrapper không: không.
    - Khung prompt ghim trong bản kê hay đọc qua `TenantOverlay`: bản kê.
    - Lời gọi model ở `simulate`: chạy thật (ADR-0111 (Accepted) quyết 3).
    - Lỗi lint ở lưu nháp hay niêm phong: như mọi lỗi `wf.*`.
    - Khung prompt mới không có ca eval (CLAUDE.md, Observability and evaluation): nay bộ `studio_llm_node_v1`.
    - `block`, `dependencies`, Khi lỗi cho phép và `x-dw-sink` của loại chưa khai.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 10 câu, sửa theo khuyến nghị: hình
  đầu ra `response`, `metadata`; schema tới model như tham số đầu ra có cấu trúc, chữ trong schema lint như
  `instructions`; `dependencies` cho `context` và khung prompt; model mặc định của tenant ở W1; `ai_description` từ phiên
  bản ghim, kiểm trường lúc gửi kiểm định và lúc chạy; lời gọi sửa mang đường dẫn lỗi và đầu ra trước trong khối bao
  chứa; lỗi khác `output_invalid` là của bộ phân giải và cổng cư trú; tài liệu chấm điểm là fixture của ticket này, tài
  liệu thật của marketing-pilot; trần 32 KiB của schema; kết quả ghim của ca kịch bản áp cho `ai.llm@2`. Không còn
  CRITICAL hay HIGH.
- 2026-11-04 (agent): MEDIUM của gate, cho người làm và cho `checking-plan-consistency`:
    - (a) "`additionalProperties: false` forced" ở ADR-0112 (Accepted) quyết 8 nên viết "required by the profile", như
      `check_profile` làm.
    - (b) Một công ty tự dựng quy trình chấm điểm có thể đưa định danh vào `prompt` ở W1: R7.4 chỉ phủ quy trình chấm điểm
      lead; luật chung theo `pd_category` là W2.
    - (c) Hai Bước dùng hai model khác nhau trong một quy trình là W2.
    - (d) Tài liệu chấm điểm của marketing-pilot phải qua test R7.4 của ticket này.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): theo gate của ticket 06: `refused_types` của `PathRules` dời về ticket
  03 (phần chung của 05 và 06), ticket này chỉ thêm `ai.llm@1` vào tập của `STUDIO_RULES`. Không thêm cạnh.
