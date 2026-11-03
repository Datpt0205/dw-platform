# 02 — Sổ đăng ký loại bước một chủ, API danh mục và bộ dựng mẫu {{ }} theo đích

Status: ready-for-agent
Blocked by: 01, .claude/plans/studio/tools-and-skills/issues/01-executor-kiem-schema-va-nha-may.md, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.4, R1.5, R4.1, R4.2, R4.3, WN1, WN2, WN13, WN15

## Mục tiêu

Ticket này làm hai việc (workflow-nodes R1.1, R1.2, R1.4, R1.5, R4.1, R4.2, R4.3; ADR-0112 (Accepted) quyết 2,
ADR-0114 (Accepted) quyết 1, 5):

- Nhận làm chủ sổ đăng ký loại bước mà wf-lite đã dựng, thay vì dựng sổ thứ hai. Thêm API danh mục đọc từ sổ đó.
- Dựng bộ dựng Chuỗi có biến `{{ }}`, render theo sáu đích; đích `prompt` bao chứa giá trị.

Kiểm `type@major` chưa đăng ký là `wf.unknown_node_type` của workflow-engine/01, đọc tập loại từ chính sổ này.

## Việc cần làm

1. **Một sổ đăng ký, không có sổ thứ hai** (ADR-0112 (Accepted) quyết 2; failure-modes #2).
    - `NodeTypeRegistry` của ADR-0112 (Accepted) là sổ wf-lite đã dựng ở `47df14d`: dataclass `NodeTypeSpec` và hàm
      `build_node_registry()` ở `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py`, với sáu loại
      `trigger.work_item@1`, `ai.llm@1`, `tool.call@1`, `human.approval@1`, `time.wait@1`, `logic.switch@1`. Từ ticket
      này, workflow-nodes làm chủ nó.
    - Sổ nằm ở lõi nền tảng vì bộ kiểm và trình biên dịch của wf-lite (`dw_agent_runtime`) đọc nó, mà hợp đồng
      "Platform core does not import Studio" cấm lõi import `dw_studio`.
    - Ticket này không viết `NodeTypeSpec` hay `build_node_registry` thứ hai trong `dw_studio`. Nó sửa dataclass và
      hàm đã có, tại chỗ.
    - `build_node_registry` từ chối hai mục cùng `type@major` bằng `ValueError`, nêu tên loại.
    - Ticket đầu tiên đăng ký một loại chỉ Studio có (ticket 03: `data.transform@1`, `flow.stop@1`) sẽ thêm hai thứ:
        - `studio_node_types(ports)` ở `packages/python/dw_studio/src/dw_studio/workflows/node_registry.py`, trả các mục
          của Studio;
        - tham số `extra` của `build_node_registry`, mà composition root của Studio truyền vào.

      Ticket này không thêm hai thứ đó, vì chưa có mục Studio nào để truyền (CLAUDE.md, Work style 6).
    - Một ticket sau mà loại của nó wf-lite đã ship (ticket 03 `logic.switch@1`, 05 `ai.llm@1`, 06 `tool.call@1` và
      `human.approval@1`) sửa đúng mục đó. Nó không thêm mục thứ hai. Sau khi sửa, mọi quy trình trong `configs/packs`
      vẫn qua bộ kiểm wf-lite và giữ nguyên nghĩa: `PackCatalog` nạp được mọi gói đã ship. Nếu không giữ được như vậy,
      ticket đó đăng ký một bản chính mới và ghi lý do.
    - Đường gói của wf-lite vẫn gọi `build_node_registry()` không có `extra`, nên chỉ thấy sáu loại (wf-lite:R2.1). Lý
      do: trình biên dịch của wf-lite chỉ chạy sáu loại đó, cho tới khi wf-lite chuyển sang `WorkflowIR` của
      workflow-engine (wf-lite, Phụ thuộc, "Kiểm lại khi"). Hai lần dựng này dùng một hàm và một bộ mục, nên một
      `type@major` chỉ có một định nghĩa.
2. **Mỗi trường vào cùng nơi đọc nó** (R1.4, WN15; failure-modes #1).
    - Ticket này thêm vào `NodeTypeSpec` chỉ những trường mà mã của chính nó đọc:
        - `label_vi`;
        - dạng khai báo của đầu ra và của Nhánh ra (bước 3).
    - Ba tính chất vị trí `opens_wait`, `ends_run`, `exits_loop` là trường bắt buộc, không giá trị mặc định. Mỗi trường
      vào cùng nơi đọc đầu tiên của nó (dòng Quyết định 3/11/2026 của spec, thay dòng 25/10/2026):
        - `ends_run` và `exits_loop` vào cùng phép hạ `lower` của workflow-engine/01, ticket chặn ticket này;
        - `opens_wait` vào cùng kiểm `wf.wait_in_parallel` của workflow-engine/06, hay cùng nơi đọc nào có trước.
    - Ticket thêm một trường bắt buộc thì khai giá trị cho mọi mục đã có lúc đó, kể cả sáu loại của wf-lite.
    - Ba nhóm trường còn lại cũng chỉ vào cùng nơi đọc của chúng:
        - nhãn năng lực, cùng phân tích của compliance-pdpl/05 (ADR-0125 (Accepted) quyết 1);
        - giới hạn kẹp theo gói, quyền và quyền lợi của loại, cùng loại đầu tiên khai chúng (R1.2, xem bước 4);
        - hook biên dịch, hành vi theo Chế độ chạy và bộ trích phụ thuộc, cùng trình biên dịch và bộ trích của
          workflow-engine.
    - Test bảng nơi đọc ở `packages/python/dw_studio/tests/workflows/test_node_registry.py`:
        - Bảng `READERS` ánh mỗi trường của `NodeTypeSpec` tới `"<module>:<qualname>"` của một nơi đọc.
        - Test đỏ khi `dataclasses.fields(NodeTypeSpec)` khác tập khóa của bảng.
        - Test cũng đỏ khi một qualname không import được, hay khi nguồn của nó (`inspect.getsource`) không chứa
          `.<trường>`.
        - Một trường có thể có nhiều nơi đọc; bảng nêu một nơi.
3. **Đầu ra và Nhánh ra ở dạng khai báo** (R1.2, R1.5).
    - `NodeTypeSpec` mang đầu ra và Nhánh ra ở dạng dữ liệu:
        - đầu ra là một schema cố định, hay "lấy từ khóa `<k>` của cấu hình";
        - Nhánh ra là một danh sách cố định có `label_vi` từng cái (`approved` "Duyệt", `rejected` "Từ chối"), hay "mỗi
          khóa của `cases` một Nhánh ra, cộng `default` 'Khác'".
    - Hai hàm `output_schema(config)` và `lanes(config)` mà mã wf-lite đang gọi được tính từ dạng khai báo đó. Chữ ký
      giữ nguyên, nên không bên gọi nào của wf-lite phải đổi, và không có mô tả thứ hai.
    - `step_output_schema(spec, config, on_error)` trả schema đầu ra của một Bước. Khi `on_error` là `continue` hay
      `route`, schema có thêm thuộc tính `error`, là `object{code: string, message: string}`. `message` là nhãn tiếng
      Việt của mã (dòng Quyết định 26/10/2026 H-21), không bao giờ là chữ của nhà cung cấp hay binding. `on_error` vắng
      thì là `fail` (R2.3) và không có `error`.
    - Danh mục (bước 4) và phạm vi biến của ticket 03 cùng gọi hàm này.
4. **Route `GET /api/v1/studio/node-types`**.
    - Route đặt ở `packages/python/dw_studio/src/dw_studio/workflows/presentation/node_types.py` và gắn vào router
      `/studio` của studio-skeleton/02.
    - Quyền là `studio.workflows.edit`, do workflow-engine/01 đăng ký. Ticket này chờ workflow-engine/01 nên không thêm
      migration. Người gọi thiếu quyền nhận 403.
    - Với mỗi loại, route trả:
        - `type`, `label_vi`;
        - schema cấu hình;
        - đầu ra ở dạng khai báo, với schema `error` và các giá trị `on_error` mà nó có mặt. Các giá trị đó là
          `continue` và `route`, theo R1.5. Tập Khi lỗi mà từng loại cho phép vào danh mục cùng trường của nó, ở ticket
          đọc nó trước (workflow-engine/01 hay ticket 03);
        - Nhánh ra cùng `label_vi`, theo tên và nhãn. Tài liệu đặt làn của Nhánh ra ở đâu (trong `config` như wf-lite,
          hay trong `lanes` như workflow-engine/01) là việc của mô hình tài liệu, MEDIUM (a);
        - `side_effect_level`.
    - Route trả thêm `catalogue_hash`.
    - Route không có tham số và không trả 404. `wf.unknown_node_type` ở mục API của spec là mã của bộ kiểm khi gửi
      kiểm định.
    - Danh mục đọc lớp nền tảng, không đọc `TenantOverlay` (CLAUDE.md, Per-tenant artifacts: inventory đọc lớp nền
      tảng).
    - Nhãn năng lực, giới hạn đã kẹp theo gói và lý do bị khoá vào danh mục trong cùng thay đổi đem trường của chúng
      tới (bước 2).
        - Ở W1 chưa loại nào mang quyền hay quyền lợi riêng: `studio.tasks.manage` và `studio.code.author` là của W2,
          theo mục API của spec.
        - Loại đầu tiên khai quyền hay quyền lợi thêm luôn phép chặn ở bộ kiểm khi gửi kiểm định, kèm test âm gọi thẳng
          lệnh gửi kiểm định. Ẩn trong danh mục không phải phân quyền (CLAUDE.md, Tenancy and authorization).
    - `catalogue_hash` là `dw_kernel.canonical.content_hash` của tài liệu danh mục chưa kẹp, do một hàm
      `catalogue_document(registry)` dựng.
        - Hai hàm `catalogue_document` và `catalogue_hash` nằm cạnh `build_node_registry` trong
          `dw_agent_runtime/wflite/registry.py`, để route và trình biên dịch của worker gọi cùng một hàm.
        - R1.1 là một test so hai mã băm. Worker không ghi hay lộ mã băm lúc chạy, vì không ai đọc (failure-modes #1).
        - Phần theo người gọi (kẹp, lý do khoá, khi chúng tới) không vào phép băm.
        - Phản hồi mang `Cache-Control: private, no-store`. Không có cache phía máy chủ.
5. **Bộ dựng mẫu**, ở `packages/python/dw_studio/src/dw_studio/workflows/templates.py` (ADR-0114 (Accepted) quyết 5).
   Module chỉ dùng `ExpressionEngine` của ticket 01, nhận qua tham số, và không import adapter.
    - Bộ dựng mẫu là thư viện có test, như engine của ticket 01. Ticket này không gắn nó vào bộ kiểm nào, và không thêm
      `x-dw-sink` vào sáu loại của wf-lite.
        - Ticket đầu tiên render một trường (ticket 03 cho bộ kiểm khi gửi kiểm định của Studio, 05 cho `ai.llm`, 06 cho
          đối số `json` của `tool.call`) khai `x-dw-sink` cho trường đó và gắn `check_template` vào bộ kiểm.
        - Đường gói của wf-lite không gọi `template_fields`. Tham chiếu nguyên giá trị `{{ params.x }}` của nó vẫn theo
          wf-lite:R3.7 cho tới khi wf-lite chuyển sang `WorkflowIR`.
    - Tokenizer:
        - đọc `{{ expr }}`; trong `expr`, nó nhận biết literal chuỗi của CEL (nháy đơn, nháy kép, ba nháy, tiền tố `r`
          hay `b`), nên `}}` trong một literal không đóng Biểu thức;
        - `\{{` là chữ `{{`;
        - `{{` không đóng, hay `{{ }}` rỗng → `template_syntax`.
    - Đích của mỗi trường cấu hình do từ khóa `x-dw-sink` trong schema cấu hình của loại khai. Hàm duyệt
      `template_fields(config_schema, config)` đọc từ khóa đó. Một chuỗi có `{{` chưa thoát, nằm ở trường không khai
      `x-dw-sink`, trả `sink_missing`. Không có đích mặc định (failure-modes #7).
    - Hai hàm của module:
        - `check_template(source, sink, env, engine) -> CheckedTemplate | list[TemplateIssue]` chạy lúc gửi kiểm định.
          Mỗi Biểu thức đi qua `ExpressionEngine.check` (trần 2 KiB mỗi nguồn là của ticket 01), và mỗi lỗi mang số thứ
          tự của Biểu thức cùng vị trí của nó trong mẫu.
        - `async render(checked, activation, engine)` trả `str`, hay một giá trị JSON ở đích `json`, hoặc
          `TemplateError(code, index)`. Lỗi không mang node: wrapper nút gắn node và đường dẫn (ticket 01, bước 1).
    - Trần, mỗi trần một mã:
        - nguồn tối đa 16 KiB (16.384 byte UTF-8) và tối đa 50 Biểu thức; vượt trần → `template_too_large` lúc gửi
          kiểm định; đúng 16.384 byte và đúng 50 Biểu thức thì qua;
        - kết quả render tối đa 64 KiB (65.536 byte UTF-8) → `render_too_large` lúc render.
    - Lỗi khi tính một Biểu thức:
        - `expression_error` hay `expression_budget_exceeded` làm cả lần render thất bại với đúng mã đó;
        - Biểu thức ra `null` ở mọi đích trừ `json` → `null_in_template`.

      Không bao giờ render thành chuỗi rỗng.
    - Đổi giá trị vô hướng ra chữ bằng một hàm `scalar_text`:
        - `string` giữ nguyên;
        - `int` viết thập phân; `double` theo `json.dumps`; `bool` thành `true` hay `false`;
        - timestamp, duration và bytes đã là chuỗi khi `evaluate` trả về (ticket 01).
    - Sáu đích:
        - **`text`**: `scalar_text`. List, map hay object → `non_scalar_in_text`: lúc gửi kiểm định khi
          `result_type` đã biết, lúc render khi kiểu là `dyn`.
        - **`html`**:
            - giá trị đi qua `html.escape(..., quote=True)`;
            - chữ tĩnh chỉ được dùng các thẻ `p br b strong i em u ul ol li a h1 h2 h3 h4 blockquote table thead tbody
              tr th td span div`;
            - thuộc tính duy nhất được dùng là `href` của `a`, với giá trị literal bắt đầu bằng `https://` hay
              `mailto:`;
            - Biểu thức chỉ đứng ở nội dung chữ, không đứng trong một thẻ.

          Vi phạm → `html_markup_not_allowed` lúc gửi kiểm định, kiểm bằng `html.parser` của stdlib. Non-scalar →
          `non_scalar_in_text`.
        - **`url`**:
            - luật này chỉ áp cho mẫu có ít nhất một Biểu thức; một URL toàn chữ tĩnh là việc của cửa ra ngoài;
            - phần literal trước Biểu thức đầu tiên phải chứa trọn scheme và authority, khớp
              `^https://[^\s/?#@{}\\]+[/?#]`; một mẫu không như vậy → `templated_host`. Các trường hợp bị từ chối gồm:
              Biểu thức ở scheme, ở host hay port, dính liền sau host (`https://api.x.vn{{ v }}`), cả URL là một Biểu
              thức, hay userinfo;
            - mỗi giá trị đi qua `urllib.parse.quote(text, safe="")`, dù ở đoạn đường dẫn, khóa hay giá trị query, hay
              fragment;
            - một đoạn đường dẫn mà toàn bộ là một giá trị bằng `.` hay `..` → `url_dot_segment` lúc render;
            - non-scalar → `non_scalar_in_text`.
        - **`header`**:
            - chỉ là giá trị header; trường tên header không khai `x-dw-sink`, nên `{{` ở đó là `sink_missing`;
            - CR, LF hay NUL trong chữ tĩnh → `header_crlf` lúc gửi kiểm định; trong giá trị đã render →
              `header_crlf` lúc render;
            - non-scalar → `non_scalar_in_text`.
        - **`json`**:
            - trường mang một giá trị JSON;
            - một lá chuỗi đúng bằng một `{{ expr }}` nhận giá trị có kiểu (kể cả `null`, list, map);
            - một lá chuỗi trộn chữ với Biểu thức render theo luật `text` thành một chuỗi;
            - kết quả là giá trị JSON để bên gọi tuần tự hóa, không bao giờ ghép thành văn bản;
            - `source` của `check_template` là giá trị JSON của cả trường. Trần 50 Biểu thức đếm trên mọi lá của
              trường; trần 16 KiB đo trên `json.dumps` của trường; trần 64 KiB của `render_too_large` đo trên
              `json.dumps` của kết quả.
        - **`prompt`**:
            - mỗi giá trị thành `contain_untrusted("v<n>", value)`, với `n` là số thứ tự (từ 1) của Biểu thức. Tên khối
              do nền tảng sinh, vì `contain_untrusted` không thoát tên (`prompts.py:35`);
            - giá trị được cắt ở 16 KiB (16.384 byte UTF-8), tại ranh giới ký tự, trước khi thoát; giá trị đúng 16.384
              byte giữ nguyên;
            - list, map hay object được tuần tự hóa
              `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))` rồi bao chứa;
            - chữ tĩnh của công ty là chỉ dẫn, nên nó:
                - không được tự viết `<input` hay `</input` (không phân biệt hoa thường) → `prompt_literal_input_tag`;
                - tối đa 8 KiB (8.192 byte UTF-8) → `prompt_literal_too_large`; cả hai lúc gửi kiểm định (ADR-0010 (Accepted);
                  ADR-0114 (Accepted) quyết 5).
            - Phép kiểm `<input` là một hàm `writes_untrusted_tag(text)` đặt cạnh `contain_untrusted`, khớp regex
              `(?i)</?input\b`. Nên `<inputs` và `<input_x` không khớp, còn `<INPUT>` và `</input>` khớp.
            - `PromptArtifact` (`prompts.py:70`, chỉ trên `template`, như hôm nay) và bộ dựng mẫu cùng gọi hàm này,
              không có bản sao thứ hai. Không prompt nào trong `configs/prompts` có thẻ đó trong `template` (đã kiểm
              ngày 3/11/2026: hai chỗ có chữ `<input>` nằm ở `system` và `description`).
    - Mỗi mã mới (`template_syntax`, `sink_missing`, `template_too_large`, `render_too_large`, `null_in_template`,
      `non_scalar_in_text`, `html_markup_not_allowed`, `templated_host`, `url_dot_segment`, `header_crlf`,
      `prompt_literal_input_tag`, `prompt_literal_too_large`) có nhãn tiếng Việt trong
      `configs/copy/run_reason_codes.d/workflow-nodes.yaml` (dòng Quyết định 26/10/2026 H-21).
6. **Test kiến trúc** trong `dw_studio` (ADR-0114 (Accepted) quyết 1):
    - cấm import `jinja2` và `string.Template`;
    - cấm gọi `.format(` và `.format_map(` trên bất cứ thứ gì không phải literal.

## Tiêu chí chấp nhận

- [ ] R1.1: một sổ (ADR-0112 (Accepted) quyết 2):
    - `rg "class NodeTypeSpec|def build_node_registry" packages apps` ra đúng một chỗ, là
      `dw_agent_runtime/wflite/registry.py`; thêm một bản thứ hai trong `dw_studio` → test đỏ;
    - hai mục cùng `type@major` → `build_node_registry` ném `ValueError` nêu tên loại;
    - `PackCatalog` nạp mọi gói trong `configs/packs`;
    - `test_wflite_validate.py` và hai test packs fail-fast của API và worker xanh, không sửa gì ngoài phần bước 3 đòi.
- [ ] R1.1: `catalogue_hash` mà route trả bằng `catalogue_hash` của sổ mà trình biên dịch của worker giữ
      (`wflite/compile.py`, `_Builder.registry`). Cho route dựng từ một sổ đã sửa một schema → hai mã băm khác nhau,
      test đỏ.
- [ ] R1.2: route trả cho mỗi loại `type`, `label_vi`, schema cấu hình, đầu ra khai báo (gồm schema `error` và các
      `on_error` của nó), Nhánh ra có nhãn (`human.approval@1`: "Duyệt", "Từ chối"; `logic.switch@1`: theo `cases`,
      cùng "Khác") và `side_effect_level`. Người gọi không giữ `studio.workflows.edit` → 403, gỡ kiểm quyền → test đỏ.
      Phản hồi có `Cache-Control: private, no-store`.
- [ ] R1.4 (WN15): thêm vào `NodeTypeSpec` một trường không có dòng trong `READERS` → test đỏ. Xóa phép đọc
      `.label_vi` khỏi nơi đọc mà bảng nêu → test đỏ.
- [ ] R1.5: `step_output_schema` của một Bước có `on_error` là `continue` hay `route` mang `error`
      (`object{code, message}`). `on_error` là `fail`, hay vắng → không có `error`. Cho `fail` công bố `error` → test đỏ.
- [ ] R4.1: cùng giá trị `<b>An</b>` render là `<b>An</b>` ở đích `text` và `&lt;b&gt;An&lt;/b&gt;` ở đích `html`.
  Thêm các ca:
    - `list[string]` ở `text` → `non_scalar_in_text`;
    - `null` ở `text` → `null_in_template`, ở `json` → `null`;
    - lá `json` đúng một `{{ x }}` với `x` là `int` → số, không phải chuỗi;
    - header có giá trị chứa `\r\n` → `header_crlf`;
    - chữ tĩnh `html` có `<script>` → `html_markup_not_allowed`;
    - mẫu 16.384 byte qua, 16.385 byte → `template_too_large`;
    - 51 Biểu thức → `template_too_large`;
    - kết quả 65.537 byte → `render_too_large`;
    - `\{{ x }}` render ra nguyên chữ `{{ x }}`;
    - `{{ "}}" }}` render ra `}}`.

  Gỡ từng phép kiểm → ca của nó đỏ.
- [ ] R4.2 (WN2):
    - lời nhắn lead chứa `</input>` render ở đích `prompt` không đóng được khối; gỡ `contain_untrusted` ở đích prompt →
      test đỏ;
    - giá trị 20.000 byte bị cắt còn ≤ 16.384 byte trước khi thoát;
    - chữ tĩnh có `<INPUT name="x">` → `prompt_literal_input_tag`; gỡ phép kiểm → test đỏ;
    - chữ tĩnh 8.193 byte → `prompt_literal_too_large`.
- [ ] R4.3 (WN13): mỗi mẫu sau ở đích `url` → `templated_host`, không render: `https://{{ trigger.input.host }}/`,
      `https://api.vi-du.vn{{ v }}/x`, `{{ u }}`, `https://{{ u }}@api.vi-du.vn/`. Còn
      `https://api.vi-du.vn/leads/{{ id }}?q={{ q }}` với `id` = `a/b` và `q` = `x&y` render ra
      `https://api.vi-du.vn/leads/a%2Fb?q=x%26y`. `id` = `..` → `url_dot_segment`.
- [ ] WN1: mẫu `{0}{x.__class__}` render ra nguyên văn. Thay tokenizer bằng `str.format` → test kiến trúc đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_node_registry.py packages/python/dw_studio/tests/workflows/test_templates.py packages/python/dw_studio/tests/workflows/test_node_types_route.py packages/python/dw_agent_runtime/tests/unit/test_wflite_validate.py` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py:30-38` và `:73`; spec: R1 (sổ đã có, hai
  trường hàm `output_schema`, `lanes`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:188`; spec: R1.1 (sổ phía worker).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:19`; spec: R1.2 (Mức tác động).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35` và `:70`; spec: R4.2
  (`contain_untrusted`, phép kiểm `<input`).
- `packages/python/dw_kernel/src/dw_kernel/canonical.py:125`; spec: R1.1 (`content_hash`).
- ADR-0112 (Accepted) quyết 2; ADR-0114 (Accepted) quyết 1, 5; ADR-0010 (Accepted); spec: R1, R4.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026, R1.3 rút: kiểm `type@major` chưa đăng ký là hàng `wf.unknown_node_type` của bảng mã workflow-engine:R2.14, làm ở workflow-engine/01.
- 2026-10-24 (agent): theo V4.24 và V4.26 của Đạt: Nhánh ra của mỗi loại là một làn Bước của tài liệu dạng cây, và `on_error: route` vào W1, nên `error` có dưới cả `continue` lẫn `route` (R1.5). Ba loại điều khiển của bậc B và ba tính chất vị trí của `NodeTypeSpec` là của ticket 07. Không thêm cạnh.
- 2026-10-25 (agent): ba tính chất vị trí của `NodeTypeSpec` chuyển từ ticket 07 về ticket này, thành trường bắt buộc không mặc định, vì bộ kiểm của workflow-engine/06 đọc chúng mà ticket 07 chờ ticket đó, và một mặc định sai là mặc định mở cho một loại chờ mới (failure-modes #7); ticket 03 khai `ends_run` của `flow.stop@1`, ticket 06 `opens_wait` của `human.approval@1`, ticket 07 `exits_loop` của `logic.break@1` (dòng Quyết định 25/10/2026 của spec, agent, tạm). Không thêm cạnh: ticket này đã là tổ tiên của workflow-engine/01 và 06.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, vì
  ticket có route; không migration). Lượt đầu CHƯA ĐẠT, với 1 CRITICAL và 9 HIGH, đều đã sửa ở ticket này, spec,
  workflow-engine/01 và 06:
    - CRITICAL: ticket viết một `NodeTypeSpec` và một `build_node_registry` thứ hai trong `dw_studio`, trong khi wf-lite
      đã ship sổ cùng tên ở `dw_agent_runtime` với bốn `type@major` trùng (`ai.llm@1`, `tool.call@1`,
      `human.approval@1`, `logic.switch@1`). Như vậy là hai sổ, trái ADR-0112 (Accepted) quyết 2. Đã sửa: một sổ, ở
      bước 1.
    - Route cần `studio.workflows.edit` của workflow-engine/01, mà workflow-engine/01 lại chờ ticket này. Đã đảo cạnh:
      ticket này chờ workflow-engine/01.
    - Ba tính chất vị trí và năm trường khác không có nơi đọc nào lúc ticket này xong, nên test của R1.4 không thể
      xanh. Nay mỗi trường vào cùng nơi đọc của nó, và R1.4 nói "ít nhất một nơi đọc có tên".
    - `catalogue_hash` không nói băm cái gì: phần theo người gọi, và hai trường kiểu hàm không băm được. Nay băm tài
      liệu danh mục chưa kẹp, dựng từ dạng khai báo.
    - Lý do khoá trong danh mục mà không có phép chặn ở bộ kiểm là ẩn thay cho phân quyền. Nay lý do khoá vào cùng phép
      chặn.
    - Trần của mẫu trái ADR-0114 (Accepted) quyết 5 và ticket 01: ticket ghi 64 KiB một mẫu. Nay là nguồn 16 KiB,
      50 Biểu thức và kết quả render 64 KiB.
    - Đích `prompt` thiếu phép kiểm `<input` và trần 8 KiB cho chữ tĩnh (ADR-0010 (Accepted)).
    - Đích `url` chỉ cấm host. Nay cấm cả scheme, phần dính liền sau host, userinfo và cả URL là một Biểu thức; giá trị
      được mã hóa phần trăm; chặn `..`.
    - Hành vi các đích còn mơ hồ: `null`, cách đổi vô hướng ra chữ, lá `json`, danh sách thẻ `html`, `header`, và
      `x-dw-sink` mặc định.
    - `error` của R1.5 mơ hồ: thuộc loại hay thuộc Bước, và dạng nào.

  Không còn gì đổi theo bản Rust, AST, kiểm độ lồng hay tham chiếu từ `check`: ticket này chỉ gọi `check` và
  `evaluate`.
- 2026-11-03 (agent): MEDIUM của gate, cho người làm và cho `checking-plan-consistency`:
    - (a) workflow-engine/01 lập kế hoạch một mô hình tài liệu `dw.workflow/v1`, một bộ kiểm và một trình biên dịch
      trong `dw_studio`, trong khi wf-lite đã dựng chúng trong `dw_agent_runtime` (`document.py`, `validate.py`,
      `compile.py`). Hai mô hình đặt làn khác nhau: wf-lite đặt trong `config`, workflow-engine/01 đặt ở `lanes` ngoài
      `config`. Ticket này chỉ gỡ phần sổ; phần còn lại là việc của gate workflow-engine.
    - (b) `human.approval@1` của wf-lite (`decision_class`, `proposal`, `locked_fields`) và của ticket 06
      (`required_scope`, người được giao, khóa chủ thể) khác hẳn nhau. Gate của ticket 06 phải nói cấu hình hợp nhất,
      hay đăng ký `@2`. Cùng câu hỏi cho `ai.llm@1` (ticket 05) và `logic.switch@1` (ticket 03, wf-lite `on` là tham
      chiếu nguyên giá trị). Một trường Studio thêm vào mục chung mà trình biên dịch wf-lite không chạy thì phải bị bộ
      kiểm wf-lite từ chối trên đường gói, không được lặng lẽ bỏ qua.
    - (c) `NodeTypeSpec.side_effect_level` của wf-lite hôm nay không ai đọc (đã kiểm: `validate.py` đọc mức của
      `ToolSpec`). Danh mục của ticket này là nơi đọc đầu tiên của nó.
    - (d) Ticket 03, 06 và 07 vẫn viết "ba tính chất vị trí bắt buộc của ticket 02"; nay chúng tới từ
      workflow-engine/01 và 06, và hành vi khai báo không đổi. Ticket 07 và 08 viết "registry của ticket 02
      (`node_registry.py`)"; nay đó là `studio_node_types` của ticket 03.
    - (e) Module trực tiếp dưới `dw_studio/workflows/` (`templates.py`, `node_registry.py`, và `ir.py` của
      workflow-engine/01) chưa nằm trong tầng nào mà `check_registration()` của studio-skeleton/02 biết.
    - (f) Một mẫu 50 Biểu thức tốn 50 vòng gửi nhận tới tiến trình tính, khoảng 50 × (149 µs + 267 µs), tức khoảng 21
      ms. Đo ở lúc đóng hàng đợi (ticket 01 MEDIUM (f), (g)).
    - (g) Đích `url` chỉ nhận `https`. Nếu cần `http` cho `local` thì quyết bằng `settings.is_deployed`, không theo
      profile.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 9 câu, sửa theo khuyến nghị:
    - bộ dựng mẫu chưa gắn vào bộ kiểm nào và không thêm `x-dw-sink` vào loại wf-lite;
    - `catalogue_document` nằm ở `dw_agent_runtime`, và R1.1 chỉ là test;
    - danh mục nêu `error` dưới `continue` và `route`; tập Khi lỗi cho phép đi cùng trường của nó;
    - Nhánh ra theo tên và nhãn; route không tham số;
    - trần của đích `json` đo trên cả trường;
    - `writes_untrusted_tag` là `(?i)</?input`, chỉ trên `template` của `PromptArtifact`;
    - luật `url` chỉ áp cho mẫu có Biểu thức, và khóa query được mã hóa.

  B7 (tầng của module) là MEDIUM (e). S4 (`null` làm hỏng lần render) là quyết định có ghi `Nếu sai thì:` ở dòng
  Quyết định 3/11/2026 của spec. Không còn CRITICAL hay HIGH.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): theo gate của workflow-engine/01 (spec workflow-engine, Quyết định
  3/11/2026): mã loại chưa đăng ký là `wf.unknown_type` mà wf-lite đã ship, không `wf.unknown_node_type`. workflow-engine/01
  thêm vào `NodeTypeSpec` bốn trường bắt buộc, `block`, `ends_run`, `exits_loop` và `dependencies`; bảng `READERS` của
  bước 2 nêu nơi đọc của chúng (`dw_agent_runtime.wflite.ir:lower` cho ba trường đầu, bộ trích ở
  `dw_studio.workflows.application` cho `dependencies`). MEDIUM (a) đã đáp: làn ở trong `config` dưới tên Nhánh ra như
  wf-lite, làn lỗi là khóa `error_lane` của Bước, không có khóa `lanes`.
