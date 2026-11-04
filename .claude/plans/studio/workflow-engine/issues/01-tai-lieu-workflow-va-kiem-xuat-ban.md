# 01 — Tài liệu dw.workflow/v1 dạng cây Bước, loại workflow, bộ kiểm khi gửi kiểm định và WorkflowIR, mở rộng tại chỗ lõi wf-lite

Status: ready-for-agent
Blocked by: .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.8, R2.1, R2.2, R2.5, R2.10, R2.11, R2.12, R2.13, R2.14, WE14, WE36

## Mục tiêu

Cho loại thành phần `workflow` của Studio đúng định dạng `dw.workflow/v1` mà wf-lite đã ship, không định dạng thứ hai:
một mô hình tài liệu, một phép hạ cây sang `WorkflowIR`, một bộ kiểm trả mọi lỗi trên IR đó và một trình biên dịch dựng
từ IR đó, cả bốn ở lõi `dw_agent_runtime.wflite`, mở rộng tại chỗ (ADR-0112 (Accepted) quyết 2, 3 và Amendments
2026-11-03; CLAUDE.md, Agent and tool rules; failure-modes #2). Gói trong `configs/packs`, bản nháp và phiên bản tenant
`+t<n>` của wf-ai và tài liệu Studio là cùng một định dạng, khác nhau ở luật theo đường (bước 3). Ticket này đăng ký
loại `workflow` vào vỏ phiên bản để một quy trình sai cây hay sai tham chiếu không niêm phong được (R1, R2 của spec;
V4.24), và cây mang làn cho mọi cấu trúc của W1 ngay từ ticket này, vì hình tài liệu là thứ đổi về sau tốn nhất.

## Việc cần làm

0. **Một chủ của `dw.workflow/v1`.**
    - wf-lite đã dựng mô hình tài liệu, sổ loại bước, bộ kiểm một lượt (cả luật sàn HITL) và trình biên dịch sang
      `StateGraph` ở `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/` (`document.py`, `registry.py`,
      `validate.py`, `compile.py`; `47df14d`). Gói `configs/packs`, trợ lý, bản nháp, mô phỏng và phiên bản tenant của
      wf-ai (`platform.dw_workflow_versions`) và leadcare dùng chúng.
    - Ticket này mở rộng các module đó tại chỗ. Nó không tạo trong `dw_studio` một `document.py`, `validator.py`,
      `ir.py`, `graph.py` hay trình biên dịch nào. Lõi không import `dw_studio` (hợp đồng "Platform core does not import
      Studio"), nên phần gói và Studio cùng dùng nằm ở lõi.
    - `dw_studio` chỉ giữ phần chỉ Studio có: `STUDIO_RULES`, mục `ArtifactKindRegistry` của `workflow`, bộ trích phụ
      thuộc, móc phát hành và `TriggerActivationPort`, ở `packages/python/dw_studio/src/dw_studio/workflows/application/`.
1. **Mô hình tài liệu**, `wflite/document.py`, mở rộng tại chỗ.
    - Giữ nguyên: `schema`, `triggers[]`, `steps[]`, `variables[]`, `decision_classes[]`, `work_kinds[]`;
      `extra="forbid"` ở mọi model (gốc, Bước, `retry`), nên `edges`, `nodes` hay một khóa vị trí không có chỗ nào để
      vào; mẫu `id` `^[a-z][a-z0-9_]{0,39}$` và mẫu `type` `STEP_TYPE` của wf-lite, một mẫu cho mọi đường.
    - `key` và `version` thành tùy chọn ở model; luật theo đường quyết chúng (bước 3).
    - Làn ở đúng chỗ wf-lite đặt: trong `config` của Bước, dưới tên Nhánh ra (`approved`, `rejected` của
      `human.approval@1`; `cases` từng giá trị và `default` của `logic.switch@1`), do `NodeTypeSpec.lanes(config)` liệt
      kê và schema cấu hình của loại khai, `additionalProperties: false`. Không có khóa `lanes` cấp Bước, nên gói đã
      ship và phiên bản `+t<n>` đã lưu đọc được như cũ, không `dw.workflow/v2`.
    - Thêm ở Bước, tùy chọn ở model, bắt buộc hay bị từ chối theo luật đường:
        - `retry`: `max_attempts` số nguyên 1-5, `backoff` `fixed` hay `exponential` (ADR-0112 (Accepted) quyết 1);
          độ trễ là của wrapper nút (ticket 03, R4.23);
        - `timeout_s`: số nguyên 1-900, trần của một lần chạy node của Bước; thời gian đỗ ở một điểm chờ không tính
          (ticket 03);
        - `on_error`: `fail`, `continue` hay `route`; ticket 07 thêm `incident`. Tập theo từng loại vào cùng loại đầu
          tiên giới hạn nó (workflow-nodes/02 bước 4);
        - `error_lane`: danh sách Bước của làn lỗi "Khi lỗi", ở cấp Bước, vì làn lỗi thuộc mọi Bước chứ không thuộc
          cấu hình của một loại.
    - Không thêm `limits`, `bindings[]`, `outcomes[]`, `inputs` hay `outputs`. Mỗi khóa vào cùng nơi đọc nó
      (failure-modes #1): `limits` ở ticket 06 (R4.20, R2.18); `bindings[]` ở ticket 05 (R2.9, lược đồ của
      tenant-config/05); `outcomes[]` ở ticket 04 (R1.9, R5.24).
    - Model không kiểm số thực hay NFC. Gói ship `default: 0.7` (`configs/packs/marketing/workflows/lead_care@1.0.0.yaml:15`)
      và được băm bằng sha256 của tệp (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:150-170`). Với loại `workflow`, lưu nháp và niêm phong đã từ
      chối qua `dw_kernel.canonical` của vỏ (tenant-config/02 bước 6 và Comments (a)); đó là R1.2.
    - Phiên bản `+t<n>` đã lưu được đọc lại bằng `WorkflowDocument.model_validate`, không qua bộ kiểm
      (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/versions.py:85-94`). Vì vậy mọi khóa thêm là tùy chọn ở model, và một dòng lưu trước ticket này vẫn đọc
      được.
2. **Phép hạ và `WorkflowIR`**, `wflite/ir.py`, mới, ở lõi.
    - `lower(document, registry) -> WorkflowIR` là nơi duy nhất đọc chỗ đặt làn. Nó dựng:
        - một node cho mỗi Bước;
        - một node gộp ở cuối mỗi khối. Trong IR nó mang một id không phải chuỗi của không gian id Bước, nên không trùng
          Bước nào. Trình biên dịch giữ đúng tên node hôm nay dùng (`join__<id>`, `wait__<id>`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:249`), vì
          checkpoint của một lượt wf-lite đang đỗ nêu các tên đó, và LangGraph cấm `:` và `|` trong tên node
          (`langgraph/graph/state.py`, `NS_END`, `NS_SEP`). Bộ kiểm từ chối một id Bước bắt đầu bằng `join__` hay
          `wait__`, hai tiền tố dành cho trình biên dịch, bằng `wf.schema_invalid` (hôm nay Bước `join__a` trùng node gộp
          của Bước `a`);
        - cạnh theo thứ tự trong làn, trừ cạnh ra khỏi một Bước mà loại khai `ends_run`;
        - cạnh điều kiện theo Nhánh ra;
        - vùng khối theo `block` của loại: `choice` (một làn chạy: rẽ nhánh, phê duyệt), `parallel` (mọi làn chạy),
          `loop` (làn `body` lặp với cạnh quay lại; làn khác, như `max_reached`, là lối ra; Bước có `exits_loop` ra
          khỏi vòng lặp);
        - vùng làn lỗi của một Bước có `on_error: route`, vào từ Bước khi nó lỗi và gộp ở node gộp của Bước đó.
    - `NodeTypeSpec` thêm ba trường bắt buộc, không giá trị mặc định: `block` (`none`, `choice`, `parallel`, `loop`),
      `ends_run`, `exits_loop`. Sáu loại wf-lite khai giá trị: `human.approval@1` và `logic.switch@1` là `choice`, bốn
      loại còn lại `none`; cả sáu `ends_run` và `exits_loop` sai. Phép hạ đọc ba trường này, không đọc tên loại.
      `opens_wait` vào cùng nơi đọc đầu tiên của nó, ticket 06 (workflow-nodes, dòng Quyết định 3/11/2026).
    - Phép hạ ngừng đi sâu quá `MAX_NESTING` (bước 4) và ghi lại chỗ ngừng, nên một cây lồng hàng trăm tầng trả
      `wf.limit_above_plan`, không `RecursionError`.
    - Mọi nơi khác của `wflite` từng đọc làn (`validate.py`, `compile.py`, `outline.py`, `assistant.py`,
      `simulate.py`) đi IR, hay hàm `iter_lanes(step, registry)` của `ir.py`, trả cả làn của loại lẫn `error_lane`.
    - Module đồ thị trong `ir.py`: `reachable(ir)` và `dominators(ir)`. `paths_to` và tập nhánh loại trừ vào cùng nơi
      đọc chúng: phân tích năng lực của ADR-0125 (Accepted) và R2.7 của ticket 06.
3. **Luật theo đường**, dataclass đóng băng `PathRules` trong `wflite/validate.py`: bốn tập khóa
   `required_document_keys`, `refused_document_keys`, `required_step_keys`, `refused_step_keys`, và cờ
   `every_port_lane` (R2.2). Luật bước áp cho mọi Bước của cây `steps[]`. Trên `triggers[]`, `retry`, `timeout_s`,
   `on_error` và `error_lane` bị từ chối ở mọi đường, vì không ai chạy chúng ở trình kích hoạt.
    - `PACK_RULES` ở lõi: bắt buộc `key`, `version`; từ chối `retry`, `timeout_s`, `on_error`, `error_lane`. Trình biên
      dịch wf-lite không chạy bốn khóa đó, nên một gói hay một đề xuất của trợ lý wf-ai mang chúng sẽ có khóa không ai
      đọc (failure-modes #1). Ticket 03 nới tập này khi trình biên dịch chạy chúng. `every_port_lane` sai: như wf-lite
      hôm nay, một làn phê duyệt vắng là làn rỗng, vì wire của trợ lý wf-ai bỏ `rejected` khi nó rỗng
      (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/assistant_wire.py:166-192`).
    - `STUDIO_RULES` trong `dw_studio.workflows.application`: từ chối `key`, `version`, vì vỏ phiên bản giữ khóa và
      `version_no` (ADR-0109 (Accepted) quyết 1, 2); bắt buộc `retry`, `timeout_s`, `on_error` ở mọi Bước (R1.1);
      `every_port_lane` đúng.
    - Vi phạm → `wf.schema_invalid` với đường dẫn tới khóa.
    - `validate()` nhận `rules` là tham số từ khóa bắt buộc, không mặc định. `PackCatalog` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:160`) và trợ lý
      (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/assistant.py:230`) truyền `PACK_RULES`.
4. **Bộ kiểm**, `wflite/validate.py`, mở rộng tại chỗ, một lượt trên IR.
    - Giữ nguyên dạng lỗi `{path, code, message_vi, message_en}`, không dừng ở lỗi đầu (R2.11), và mọi kiểm wf-lite đã
      có. Luật sàn HITL (wf-lite R4) chạy như nhau trên mọi đường, không bao giờ nhẹ hơn cho Studio.
    - R2.1 `wf.unreachable_node`: một Bước trong làn đứng sau một Bước mà loại khai `ends_run` hay `exits_loop`, theo
      `reachable`.
    - R2.2 `wf.router_not_total`:
        - mọi đường: `logic.switch@1` thiếu làn `default` → mã, kiểm wf-lite giữ nguyên (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:280`);
        - khi `every_port_lane` đúng (Studio): mỗi Nhánh ra mà `spec.lanes(config)` trả phải có khóa của nó trong
          `config` (`cases` thì từng giá trị dưới `cases`); `[]` là có (một phê duyệt mà "Từ chối" không làm gì viết
          `rejected: []`). `error_lane` và làn `max_reached` được miễn.
    - R2.5 `wf.ref_not_dominating`: tham chiếu nguyên giá trị `{{ steps.<id>.<trường> }}` (wf-lite R3.7) theo
      `dominators(ir)`, thay các tập `visible` của lượt đi hôm nay. Lượt tìm tham chiếu bỏ qua đúng các khóa làn mà IR
      nêu cho Bước đó, thay danh sách viết cứng `_NOT_VALUES` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:38`), nên làn `body` của một loại mới không
      bị đọc như giá trị cấu hình. Hai ca trả mã: tham chiếu từ sau khối tới một Bước
      chỉ có ở một làn của khối, và tham chiếu tới một Bước của làn lỗi. Biểu thức CEL và `has()` là của
      workflow-nodes/03 (R3.2, R3.3), nơi CEL vào bộ kiểm này.
    - R2.10 `wf.limit_above_plan`, hai trần nền tảng là hằng ở lõi, như nhau cho mọi tenant và mọi đường, không tra
      cứu gì nên không có chỗ mở khi tra cứu lỗi:
        - `MAX_TREE_STEPS = 500` Bước của cây, đếm mọi làn ở mọi độ sâu, kể cả làn lỗi, không đếm `triggers[]`;
        - `MAX_NESTING = 10`: Bước ở `steps[]` có độ sâu 1, Bước trong một làn (kể cả `error_lane`) của Bước độ sâu n
          có độ sâu n + 1.

        Đúng 500 Bước và đúng độ sâu 10 thì qua. Con trỏ tới Bước đầu tiên vượt.

    - R1.8: `edges`, `nodes`, hay một khóa vị trí ở bất cứ đâu → `wf.schema_invalid` (từ `extra="forbid"`); một khóa
      làn mà loại không khai, như `expired` trên `human.approval@1` (W2) → `wf.config_invalid` (từ schema của loại);
      `error_lane` khi `on_error` khác `route`, hay `on_error: route` không có `error_lane` → `wf.schema_invalid`.
    - R2.14: `type@major` không có trong sổ → `wf.unknown_type`, mã wf-lite đã ship (wf-lite R2.2), không thêm
      `wf.unknown_node_type`.
    - Bảng mã: `MESSAGES` trong `validate.py` là bảng `wf.*` duy nhất của kho, song ngữ vi/en. Mã mới
      (`wf.unreachable_node`, `wf.limit_above_plan`) vào bảng đó. Một kiểm ở `dw_studio` hay ở ticket sau dựng lỗi bằng
      `Problem.of`, không có bảng riêng.
    - Chế độ cảnh báo (R2.13) là cùng hàm `validate`; bên gọi quyết: lưu nháp trả cảnh báo, niêm phong trả 422.
5. **Trình biên dịch wf-lite dựng từ `WorkflowIR`** (R2.12, WE14).
    - `_Builder` của `compile.py` dựng chuỗi, khối phê duyệt và khối rẽ nhánh từ vùng của `lower(...)`, thay `_lanes`
      riêng của nó (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:213`). Hành vi trên gói không đổi.
    - Ticket 03 mở rộng chính trình biên dịch này (retry, `timeout_s`, `on_error`, làn lỗi, wrapper nút), không viết
      trình biên dịch thứ hai.
6. **Phía Studio**, `dw_studio/workflows/application/`.
    - Mục `workflow` của `ArtifactKindRegistry`, đăng ký ở `build_studio` (seam của tenant-config/02 bước 5):
        - `kind` `workflow`, `document_schema` `dw.workflow/v1`;
        - khóa đọc `studio.workflows.read`, khóa ghi `studio.workflows.edit`, khóa gửi `studio.versions.submit`
          (R1.5, tenant-config:R2.15);
        - `validate`: hàm lõi `validate(document, registry=..., rules=STUDIO_RULES, tools=..., work_schemas={})`.
          Sổ là sổ composition root dựng: `build_node_registry()` (sáu loại) tới khi workflow-nodes/03 thêm
          `extra=studio_node_types(ports)`. `tools` là `ToolSpecRegistry` của `container.runtime`, lớp nền tảng (`tenant_id=None`) như wf-lite; công cụ của
          tenant vào cùng workflow-nodes/06. Đường dẫn của lỗi
          thành con trỏ JSON `/` + đường dẫn;
        - `extract`: bộ trích của bước 7;
        - `publish_hook`: bước 8.
    - Bước niêm phong của tenant-config/02 gọi `validate` này (R1.4).
    - Cảnh báo khi lưu nháp (R2.13): `ArtifactService.save_draft` của tenant-config/02 gọi `validate` của mục loại
      sau khi lưu, và trả lỗi thành `warnings[]` trong thân 200. Không lỗi `wf.*` nào chặn việc lưu, kể cả
      `wf.schema_invalid` của một nháp còn trống (`steps: []`); chỉ lỗi băm của R1.2 chặn. Như nhau cho mọi loại; hai loại
      fixture trả `[]`. Sinh lại snapshot OpenAPI và kiểu TS.
    - `dw_studio` thêm phụ thuộc `dw-agent-runtime` (`packages/python/dw_studio/pyproject.toml`, `IMPORT_TO_DIST` của
      `scripts/verify_architecture.py`). Nó chỉ import `dw_agent_runtime.wflite.document`, `registry`, `ir`,
      `validate`.
    - `lint-imports` xanh, nhất là "LangGraph only in Studio compilers", hợp đồng cấm cả chuỗi import gián tiếp. Phải
      chạy và nhìn (failure-modes #4). Nếu một chuỗi tới `langgraph` hiện ra, các hàm lõi tới Studio qua `build_studio`
      từ `container.runtime`, không qua import.
7. **Bộ trích phụ thuộc** (`dependencies.py`): thuần, đi IR, mọi Bước ở mọi độ sâu, kể cả làn lỗi và `triggers[]`.
    - Một dòng `node_type` cho mỗi `type@major` khác nhau.
    - Dòng `artifact` từ trường mới, bắt buộc, không mặc định, `NodeTypeSpec.dependencies(config)`: trả các bộ
      `(to_kind, to_key, usage, path)` theo hợp đồng `extract` của tenant-config/02 bước 5. Sáu loại wf-lite trả `()`,
      vì công cụ và prompt của chúng là của nền tảng, không là thành phần Studio.
    - Dòng `binding` là của bộ trích chung của tenant-config/05 (bước 1 của ticket đó), cùng `bindings[]`.
8. **Đăng ký, quyền, móc phát hành.**
    - `publish_hook` của `workflow` (R1.6; ADR-0109 (Accepted) quyết 1) gọi Protocol `TriggerActivationPort`, khai ở
      `dw_studio.workflows.application.ports` (bên dùng khai; CLAUDE.md, Non-negotiable architecture), cho phiên bản
      vừa lên `live`, trên đúng giao dịch phát hành mà agent-lifecycle/04 mở ở handler `.decided` và truyền cho móc
      (agent-lifecycle:R5.5). Móc không đổi giai đoạn và không ghi `studio.version.published` (tenant-config/02,
      bước 5).
    - Hợp đồng của port:
        - sau lời gọi, các đăng ký `active` của thành phần là đúng của phiên bản đó; đăng ký của phiên bản trước thành
          `retired` (workflow-triggers/01 bước 1);
        - gọi lại cho cùng phiên bản không đổi gì, vì outbox có thể giao lại `.decided`;
        - lỗi của port ném ra, và cả giao dịch phát hành lùi.
    - workflow-triggers/01 đáp ứng port. Composition root nối bản thật ở `build_studio`. Test của ticket này dùng một
      bản giả theo đúng hợp đồng trên. Lời gọi `ActorBoundaryPort` (R1.7) vào cùng móc ở ticket 03.
    - Migration (id hex ngẫu nhiên): INSERT dòng `workflow` vào `studio.artifact_kinds` với `has_quality_gate = true`
      (OPS-b, tenant-config:R2.14). Đăng ký `studio.workflows.read`, `studio.workflows.edit` và khóa thử
      `studio.workflows.test` (H-19; route `test-runs` của workflow-triggers/01 và route Bước chạy của
      telemetry-and-audit/03 kiểm nó, workflow-triggers:R2.3, telemetry-and-audit:R4.4) vào danh mục quyền theo quy
      ước khóa của tenant-rbac/01.
    - Câu INSERT vào `platform.permissions` nêu mọi cột NOT NULL không DEFAULT lúc đó: `key`, `area`, `label_vi`,
      `scope_kind`, `risk`, `status`, `owner_package` (tenant-rbac/01) và `tenant_grantable` (tenant-rbac/02). Giá trị
      theo luật phân loại ở bước 3 của tenant-rbac/01 và bước 1 của tenant-rbac/02 (V4.P2).
    - `studio.versions.submit` do agent-lifecycle/03 đăng ký; ticket này không đăng ký lại (V4.P12).
    - Chưa route nào của ticket này kiểm `studio.workflows.test`. Cùng thay đổi thêm khóa đó vào danh sách ngoại lệ của
      kiểm (c) "mọi khóa `active` có ít nhất một chỗ kiểm" ở test của tenant-rbac/01 (tenant-rbac:R1.2), lý do "chỗ
      kiểm ở workflow-triggers/01 và telemetry-and-audit/03 (H-19)". Chỗ kiểm đầu tiên gỡ mục đó.
9. **Fixture.**
    - Một sổ loại giả dùng chung cho test lõi và test Studio: một Bước có hiệu ứng, một `choice`, một Bước chờ, một
      `parallel`, một `loop` (làn `body`, `max_reached`), một Bước `ends_run`, một Bước `exits_loop`, một trình kích
      hoạt có `dependencies` tới một Nguồn dữ liệu kind `endpoint`, một Bước có `dependencies` tới một object.
    - Tài liệu mẫu của quy trình Tiếp nhận lead (15 Bước, một Bước phê duyệt với làn "Duyệt" và "Từ chối") làm fixture
      biên dịch và chạy ở ticket 03.

## Tiêu chí chấp nhận

- [ ] R2.12 (WE14): một chủ: `rg "class WorkflowDocument|def lower\(|class NodeTypeSpec|def compile_workflow|^MESSAGES" packages apps`
      ra đúng một chỗ mỗi tên, trong `dw_agent_runtime/wflite`; test kiến trúc đỏ khi thêm bản thứ hai vào `dw_studio`.
- [ ] R1.1: gói và `+t<n>` giữ nguyên:
    - `PackCatalog` nạp mọi gói trong `configs/packs` không lỗi nào;
    - một nội dung `+t<n>` lưu trước ticket này (chép từ fixture của wf-ai) đọc được qua `tenant_pinned`;
    - `test_wflite_validate.py`, các test của wf-ai và hai test packs fail-fast của API và worker xanh;
    - graph biên dịch của `lead_care@1.0.0` có đúng tập node và tập cạnh của snapshot ghi ở commit gốc của ticket, kể
      cả tên node gộp và node chờ.
- [ ] R1.1: trên đường Studio, Bước thiếu `retry`, `timeout_s` hay `on_error`, nằm ba tầng (trong `error_lane` của một Bước
      nằm trong làn `approved`) → niêm phong 422 `wf.schema_invalid` có con trỏ tới khóa thiếu. Một cây hợp lệ có Bước
      trong làn rẽ nhánh, làn phê duyệt và làn lỗi thì qua. `timeout_s` 0 hay 901, `max_attempts` 0 hay 6 → từ chối;
      `timeout_s` 1 và 900, `max_attempts` 1 và 5 → qua.
- [ ] R1.1: luật đường: tài liệu gói có `on_error` ở một Bước, hay đề xuất của trợ lý wf-ai có `error_lane` →
      `wf.schema_invalid`, gói không nạp, đề xuất không ra. Tài liệu Studio có `key` → `wf.schema_invalid`. Một trình kích hoạt
      có `retry` → `wf.schema_invalid` ở cả hai đường. Một Bước id `join__a` → `wf.schema_invalid`. Gỡ một tập của
      `PACK_RULES` → test đỏ.
- [ ] R1.8 (WE36): `edges` ở gốc, `position` trong một Bước, khóa làn `expired` trên `human.approval@1`, `error_lane`
      trên Bước có `on_error: fail`, hay `on_error: route` không có `error_lane` → từ chối có con trỏ, không niêm
      phong. Gỡ `extra="forbid"` khỏi `Step` → hai tài liệu chỉ khác `position` niêm phong ra hai mã băm định nghĩa
      khác nhau, test đỏ.
- [ ] R1.2: `PUT` nháp `workflow` có `{"score": 1.0}` → 422 `float_forbidden` có con trỏ; chuỗi NFD → `not_nfc`; không
      mã băm nào được ghi. Gói `lead_care` với `0.7` vẫn nạp.
- [ ] R1.3: niêm phong một nháp có trình kích hoạt fixture dùng một Nguồn dữ liệu, và một Bước fixture tới một object
      nằm trong `error_lane` của một Bước trong làn `approved` → `studio.dependencies` có dòng `node_type` của Bước lồng
      đó và dòng `artifact` của cả hai. Cho bộ trích chỉ đi `steps[]` cấp đầu → test đỏ. Cho `dependencies` của loại
      fixture trả `()` → test fixture đỏ.
- [ ] R1.4: `ArtifactKindRegistry` và các dòng `studio.artifact_kinds` cùng có `workflow` (test so hai tập của
      tenant-config/02). Niêm phong `workflow` gọi bộ kiểm của ticket này. Mục `workflow` có `publish_hook` (test
      composition root của tenant-config/02); gỡ móc khỏi mục → test đó đỏ.
- [ ] R1.6: gọi `publish_hook` của `workflow` cho một phiên bản trong một giao dịch thử → bản giả của
      `TriggerActivationPort` nhận đúng một lời gọi cho phiên bản đó, trong cùng giao dịch. Các ca khác:
    - giao dịch lùi → bản giả không còn đăng ký nào;
    - gọi lần hai cho cùng phiên bản → không thêm đăng ký;
    - bản giả ném lỗi → giao dịch phát hành lùi, `stage` không đổi;
    - `stage` của phiên bản không đổi, và không dòng `studio.version.published` nào;
    - gỡ lời gọi port khỏi móc → test đỏ.
- [ ] R1.5: mục `workflow` khai ba khóa đúng tên, và dòng `studio.artifact_kinds` có `has_quality_gate = true`.
      `platform.permissions` có dòng `studio.workflows.test` với `tenant_grantable` theo luật của tenant-rbac/02, và
      kiểm (c) của tenant-rbac/01 xanh nhờ mục ngoại lệ có lý do. Các ca âm:
    - bỏ khóa khỏi migration → test của R1.5 đỏ;
    - bỏ mục ngoại lệ → kiểm (c) đỏ và nêu khóa;
    - test kiểm quyền tham số hóa của tenant-config/02 chạy cho `workflow`: thiếu `studio.workflows.read` → `GET`
      thành phần 404; có khóa đọc mà thiếu `studio.workflows.edit` → `PUT` nháp 403;
    - thành viên tenant B giữ cả ba khóa, `GET` và `PUT` nháp một `workflow` của tenant A → 404;
    - gỡ khóa đọc khỏi mục → test registry đỏ.
- [ ] R2.1: `NodeTypeSpec`: dựng một mục thiếu `block`, `ends_run`, `exits_loop` hay `dependencies` → lỗi lúc dựng; sáu loại
      wf-lite khai cả bốn. Cho `ends_run` mặc định `False` → test dựng mục thiếu nó đỏ.
- [ ] R2.1: Bước đứng sau Bước fixture `ends_run` trong cùng làn, hay sau Bước `exits_loop` trong làn `body` →
      `wf.unreachable_node` có con trỏ tới Bước đó.
- [ ] R2.2: `logic.switch@1` thiếu `default` → `wf.router_not_total`; `human.approval@1` không có khóa `rejected` →
      `wf.router_not_total` trên đường Studio, có `rejected: []` → qua; cùng phê duyệt trên đường gói → qua (đề xuất
      chỉ có `approved` của test wire wf-ai vẫn xanh); Bước `loop` fixture không có làn `body` → `wf.router_not_total`;
      Bước `on_error: fail` không có `error_lane`, hay `loop` không có `max_reached` → qua.
- [ ] R2.5: tham chiếu từ sau một khối `choice` tới đầu ra của một Bước chỉ có ở một làn của khối →
      `wf.ref_not_dominating`; tham chiếu từ sau Bước lỗi tới một Bước của `error_lane` của nó →
      `wf.ref_not_dominating`; tham chiếu tới một Bước đứng trước khối → qua. Các ca dominance của wf-lite giữ kết quả.
- [ ] R2.10: cây 501 Bước → `wf.limit_above_plan`, 500 Bước → qua; độ sâu 11 chỉ bằng `logic.switch@1` lồng nhau →
      `wf.limit_above_plan`, độ sâu 10 → qua; cây lồng 200 tầng → 422 có mã trong dưới 1 giây, không `RecursionError`.
- [ ] R2.11: tài liệu có sáu lỗi ở các độ sâu khác nhau của cây → bộ kiểm trả cả sáu trong một lần, mỗi lỗi một con
      trỏ.
- [ ] R2.12 (WE14): quét nguồn `dw_agent_runtime/wflite` và `dw_studio`: lời gọi `.lanes(` và lần đọc khóa
      `error_lane` chỉ có ở `wflite/ir.py`, và `_NOT_VALUES` không còn; thêm một lời gọi `.lanes(` vào `compile.py` →
      test đỏ. Cho `lower` bỏ
      `error_lane` → ca R2.5 của Bước trong làn lỗi lồng trong làn `approved` không ra lỗi, test đỏ.
- [ ] R2.13: `PUT` nháp có một Bước không tới được → 200, tài liệu được lưu, `warnings[]` có `wf.unreachable_node`;
      niêm phong cùng tài liệu → 422. `PUT` nháp `steps: []` → 200 với cảnh báo `wf.schema_invalid`.
- [ ] R2.14: niêm phong tài liệu có Bước `foo.bar@1` → 422 `wf.unknown_type` có con trỏ tới Bước, không niêm phong;
      lưu nháp cùng tài liệu chỉ cảnh báo.
- [ ] R2.11: bảng mã: mọi chuỗi `"wf.<mã>"` trong mã nguồn của `packages/` và `apps/` là một khóa của `MESSAGES`, có cả chữ vi
      lẫn en. Thêm một chuỗi mã không có trong bảng → test đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/document.py:30-73`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py:30-38`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:118-130` và `:280`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:213` và `:249`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/versions.py:85-94`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:150-170`; spec: R1, R2, WE14, WE36, Hiện trạng.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:294`; spec: R1, R2.
- tenant-config:R2.6 (bước niêm phong gọi bộ kiểm), R2.15 (móc phát hành của mục loại), R3.1 (Nơi đang dùng), R1.2
  (dạng chuẩn); agent-lifecycle:R5.5 (gọi móc trong giao dịch phát hành); ADR-0109 (Accepted) quyết 1;
  ADR-0112 (Accepted) quyết 1, 2, 3 và Amendments 2026-11-03; ADR-0128 (Proposed), D17 đường C; V4.24.

## Comments

- 2026-10-23 (agent): DO-05 và DO-06 đã có lời đáp (Đạt 23/10/2026), nên ticket về `needs-triage`. Theo phiếu cùng ngày: bảng mã `wf.*` duy nhất kể cả `wf.unknown_node_type` (A:workflow-engine:R2.2~workflow-nodes:R1.3), dòng `workflow` trong `studio.artifact_kinds` (OPS-b), khóa `studio.workflows.edit` đăng ký ở đây.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: loại `workflow` khai khóa đọc `studio.workflows.read` mà ticket này đăng ký, khóa ghi và khóa gửi (R1.5), và dòng `studio.artifact_kinds` nêu `has_quality_gate`.
- 2026-10-24 (agent): vòng sửa thứ tư: năm mã `wf.*` đổi theo ADR-0112 (Accepted) quyết 3 (phát hiện F về ADR-0112 (Accepted) và R2); ticket chờ agent-lifecycle/03, nơi đăng ký `studio.versions.submit` (V4.P12, I:agent-lifecycle/03~workflow-engine/01), và tenant-rbac/02, vì câu INSERT khóa nêu `tenant_grantable` (V4.P2); khóa dẫn quy ước của tenant-rbac/01 (V4.P10).
- 2026-10-24 (agent): lượt c của vòng 4: mục `workflow` mang `publish_hook` gọi `TriggerActivationPort`, Protocol ticket này khai và workflow-triggers/01 đáp ứng bằng việc ghi `studio.trigger_subscriptions` trong giao dịch phát hành (R1.4, R1.6; ADR-0109 (Accepted) quyết 1); không thêm cạnh: agent-lifecycle/04, nơi gọi móc, và workflow-triggers/01 cùng đã chờ ticket này qua workflow-engine/04.
- 2026-10-24 (agent): lượt d của vòng 4: dòng Comments của lượt c thôi dẫn mã mục của lượt; bước 5 ghi rằng ticket 03 thêm vào cùng móc lời gọi `ActorBoundaryPort` của R1.7, vì record-access đòi móc của loại `workflow` ghi giới hạn dữ liệu của phiên bản trong giao dịch phát hành (record-access:R6.7) và ticket 03 đã chờ record-access/04; ticket này không thêm cạnh nào.
- 2026-10-24 (agent): theo V4.24 và V4.26 của Đạt, ticket viết lại cho tài liệu cây Bước: `steps[]` với `lanes` theo Nhánh ra thay `nodes[]` và `edges[]`, `timeout_s` thay `timeout_ms` như ADR-0112 (Accepted) quyết 1, dạng `type` nhận tên có dấu chấm, một phép hạ duy nhất sang `WorkflowIR`, bộ trích đi mọi độ sâu của cây, và R1.8 cùng WE36 mới; R2.3, R2.4 rút vì cây không viết được hai ca đó, R2.7 sang ticket 06 cùng các kiểm của làn song song. Không thêm cạnh.
- 2026-10-24 (agent): kiểm lượt g của vòng 4: R2.2 của spec nói mọi Bước thiếu làn cho một Nhánh ra mà loại khai, không chỉ Bước rẽ nhánh, vì workflow-nodes/07 dẫn R2.2 cho thân vòng lặp, nên tiêu chí R2.2 thêm Bước vòng lặp không mang làn `body`; R2.10 đo độ sâu lồng của cả cây như ADR-0112 (Accepted) quyết 3, thay độ sâu lồng của khung chứa, nên tiêu chí R2.10 thêm ca chỉ lồng `logic.switch`. Không thêm cạnh.
- 2026-10-25 (agent): phép hạ đọc `ends_run` và `exits_loop` của `NodeTypeSpec` (trường bắt buộc của workflow-nodes/02) thay tên loại `flow.stop` và `logic.break` để biết Bước nào không có cạnh ra hay ra khỏi vòng lặp (R2.1; dòng Quyết định 25/10/2026 của workflow-nodes). Không thêm cạnh: ticket này đã chờ workflow-nodes/02.
- 2026-10-25 (agent): lượt h, theo H-19: `studio.workflows.test` đăng ký ở đây cùng các khóa khác của loại `workflow` (bước 5, R1.5), dời từ workflow-triggers/01, vì route `test-runs` của ticket đó và route Bước chạy của telemetry-and-audit/03 cùng kiểm nó và ticket này là tổ tiên của cả hai; khóa nằm ở danh sách ngoại lệ của kiểm (c) của tenant-rbac/01 tới khi chỗ kiểm đầu tiên có. Không thêm cạnh.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): theo gate của workflow-nodes/02 (dòng Quyết định 3/11/2026 của workflow-nodes): `NodeTypeRegistry` là sổ wf-lite đã có (`dw_agent_runtime/wflite/registry.py`), nên ticket này thôi chờ workflow-nodes/02, và workflow-nodes/02 chờ ticket này vì route danh mục cần `studio.workflows.edit`. Mỗi trường của `NodeTypeSpec` vào cùng nơi đọc đầu tiên của nó: ticket này thêm `ends_run` và `exits_loop` (bắt buộc, không mặc định, khai cho mọi mục đã có, kể cả sáu loại wf-lite) cùng phép hạ `lower`, và cả chính sách Khi lỗi cho phép của loại nếu bộ kiểm của ticket này đọc nó; tiêu chí cho gate của ticket này: một mục thiếu một trong hai trường → `build_node_registry` lỗi, cho hai trường mặc định `False` → test đỏ.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary
  walk, vì ticket có migration; không route mới, chỉ thêm `warnings[]` vào thân trả của `PUT .../draft`). Lượt đầu CHƯA
  ĐẠT, 1 CRITICAL và 10 HIGH, đều sửa ở ticket này, spec, ADR-0112 (Accepted) Amendments 2026-11-03 và CLAUDE.md:
    - CRITICAL: ticket dựng `dw.workflow/v1` thứ hai (mô hình, bộ kiểm, IR, trình biên dịch) trong `dw_studio`, trong khi
      wf-lite đã ship đủ bốn ở `dw_agent_runtime.wflite`, dùng bởi gói và phiên bản `+t<n>` của wf-ai;
      ADR-0112 (Accepted) quyết 2, 3 cho một sổ và một bộ kiểm trên IR của trình biên dịch. Sửa: mở rộng tại chỗ (bước 0-5).
    - Làn ở khóa `lanes` riêng sẽ từ chối mọi gói và mọi dòng `+t<n>` (`extra="forbid"`). Sửa: làn trong `config` như
      wf-lite, làn lỗi là `error_lane`.
    - `retry`, `timeout_s`, `on_error` bắt buộc và số thực bị từ chối ở model sẽ từ chối `lead_care` (`0.7`, không
      `retry`). Sửa: tùy chọn ở model, bắt buộc theo `STUDIO_RULES`; số thực bị từ chối ở chỗ băm (R1.2).
    - Trình biên dịch wf-lite không chạy bốn khóa mới, nên một gói hay đề xuất wf-ai mang chúng có khóa không ai đọc.
      Sửa: `PACK_RULES` từ chối chúng.
    - Hai bảng mã: `wf.unknown_node_type` của spec cạnh `wf.unknown_type` đã ship. Sửa: `MESSAGES` là chủ, mã đã ship
      giữ tên.
    - Phép hạ không đọc tên loại mà không có trường nào nói khối chạy một làn, mọi làn hay lặp. Sửa: `block`.
    - R2.6 và `has()` của R2.5 cần `ExpressionEngine` và bộ dựng mẫu, mà ticket không chờ và workflow-nodes/02 chờ
      ticket này. Sửa: sang workflow-nodes/03 (spec, Ngoài phạm vi).
    - R2.9 không có `bindings[]` để so, lược đồ của nó là của tenant-config/05, và quét id kết nối trùng
      tenant-config:R7.1. Sửa: R2.9 sang ticket 05, hẹp lại; dòng `binding` của R1.3 là của tenant-config/05.
    - R2.10 không có nguồn trần, mở khi tra cứu lỗi, và cây lồng sâu làm `RecursionError` trước khi kiểm. Sửa: hai
      trần nền tảng, phép hạ ngừng ở trần.
    - Hợp đồng `TriggerActivationPort` không nói thay đăng ký của phiên bản trước, gọi lại, hay lỗi. Sửa: bước 8.
    - R2.13 không ai trả cảnh báo: `save_draft` của tenant-config/02 không gọi bộ kiểm. Sửa: bước 6.

    Lượt xác nhận (một subagent mới, builder check với ba bước của boundary walk, đọc thêm mã wf-lite) tìm 2 HIGH, sửa
    theo khuyến nghị: tên node gộp `join:<id>` mà LangGraph cấm (`NS_END`) và làm hỏng checkpoint của lượt wf-lite đang
    đỗ (nay giữ `join__<id>`, `wait__<id>` và cấm hai tiền tố ở id Bước); R2.2 trên đường gói từ chối đề xuất wf-ai
    thiếu `rejected` (nay `every_port_lane` chỉ ở Studio). Cũng sửa theo lượt đó: bốn khóa mới bị từ chối ở
    `triggers[]`, `_NOT_VALUES` nhường cho khóa làn của IR, lưu nháp không bị chặn bởi lỗi `wf.*`, nghĩa của `timeout_s`.
    Quyết định này đứng trên mã đã ở `main` (`47df14d`, `3c85dbd`), không trên trạng thái của ADR-0128 (Proposed).

- 2026-11-03 (agent): MEDIUM của gate, chưa sửa, cho người dựng và cho `checking-plan-consistency`:
    - (a) đường dẫn lỗi thành con trỏ JSON: một giá trị `cases` chứa `/` hay `~` phải thoát theo RFC 6901; `_join` của
      wf-lite hôm nay không thoát;
    - (b) tham chiếu tới trường đầu ra của một Bước `on_error` `continue` hay `route` qua kiểm thống trị mà có thể vắng
      lúc chạy; `has()` của workflow-nodes/03 và wrapper của ticket 03 quyết;
    - (c) `ai.llm@1` của Studio với `min_confidence: 0.7` bị dạng chuẩn từ chối (số thực); workflow-nodes/05 nhận chuỗi
      thập phân hay tham số;
    - (d) `.decided` của v3 giao lại muộn sau khi v4 đã `live`: port chỉ lũy đẳng theo phiên bản; handler của
      agent-lifecycle/04 không được phát hành lại một phiên bản không còn là bản đang phát hành;
    - (e) gỡ đăng ký kích hoạt khi Đóng băng, Tắt khẩn hay thu hồi là của agent-lifecycle và workflow-triggers;
    - (f) Studio bắt buộc `retry`, `timeout_s` ở mọi Bước, cả `logic.switch@1`: canvas (workflow-builder-ui) ghi giá trị
      mặc định theo loại;
    - (g) sàn HITL nhận cổng theo tên `human.approval@1` và `approved` ở `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:247` và `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:443`, một luật
      hai chỗ; ticket 03 có thể dời về IR;
    - (h) ma trận quyền: lệnh gửi thiếu `studio.versions.submit` là ca âm của agent-lifecycle/03; ticket này thêm ca
      tenant B ở R1.5;
    - (i) đã có câu trả lời: id Bước trùng ở mọi độ sâu là `wf.duplicate_step_id` của wf-lite (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:212-214`);
      model đóng ở mọi tầng là `extra="forbid"`; mã băm định nghĩa băm `content_hash` của tài liệu (tenant-config/02
      bước 6), nên ca "gỡ kiểm" của R1.8 đỏ được.
- 2026-11-03 (agent): việc các ticket sau phải đổi, ghi ở Comments của từng ticket: 03 (trình biên dịch lõi, tên node,
  một cache, `PACK_RULES`), 04 (`outcomes[]` vào model lõi), 05 (R2.9, `bindings[]`), 06 (`limits`, `opens_wait`, làn
  trong `config`), 07 (`incident`), 09 (kiểm trên bao đóng ở `dw_studio`, mã trong `MESSAGES`); 02 và 08 không đổi.
  Ngoài khu: workflow-nodes/02 (mã `wf.unknown_type`, bốn trường mới của `NodeTypeSpec` trong `READERS`, MEDIUM (a)
  đã đáp), workflow-nodes/03 (R2.6, `has()`).
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
