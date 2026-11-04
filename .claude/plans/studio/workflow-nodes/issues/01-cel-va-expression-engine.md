# 01 — Cổng ExpressionEngine, adapter CEL trong tiến trình tính riêng, thư viện dw.cel/v1 và bộ test hợp đồng

Status: resolved (2026-11-04, 73ee226)
Blocked by: .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md
Area: studio
Yêu cầu: R3.1, R3.4, R3.7, WN12, WN36

## Mục tiêu

Ticket này dựng nền biểu thức của Studio (workflow-nodes R3.1, R3.4, R3.7, WN12, WN36; ADR-0114 (Accepted) quyết 2-4,
Amendments 2026-11-03):

- một Protocol `ExpressionEngine` thuần stdlib ở `dw_kernel.expressions`;
- một adapter `CelCppEngine` trên `cel-expr-python==0.1.3` ở `dw_studio.core.adapters.cel`, tính trong tiến trình
  tính riêng có đồng hồ 1 giây;
- thư viện `dw.cel/v1` của W1;
- một bộ test hợp đồng mà mọi adapter thay thế phải qua.

FOG-50 đã được đo ở gate ngày 3/11/2026 và số đo nằm trong ADR-0114 (Accepted), nên ticket này không có nhánh thử. Bản Rust và
setting chọn binding đã bị bỏ (spec R3.6 [Bỏ], Ngoài phạm vi). Hai route `/expressions/check` và
`/expressions/evaluate` (R3.5) thuộc ticket 03.

## Việc cần làm

1. `packages/python/dw_kernel/src/dw_kernel/expressions.py` (chỉ stdlib):
    - Đại số kiểu đóng của ADR-0114 (Accepted) quyết 2 (`null`, `bool`, `int`, `double`, `string`, `bytes`, `timestamp`,
      `duration`, `list[T]`, `map[string, T]`, `object{...}`, `optional[T]`, `dyn`), viết dạng dataclass đóng băng.
      `object{...}` mang tên và các trường có kiểu.
    - `ExpressionEnv(tenant_id: TenantId | None, variables: Mapping[str, ExprType], library: str)`. `tenant_id` là
      `None` ở lớp nền tảng. `env_hash()` băm ổn định các biến và kiểu, sắp theo tên, và không gồm tenant.
    - `CheckedExpression(source, env, result_type)`.
    - `ExpressionIssue(kind, line, column, name, message)`, với `kind` thuộc tập đóng `syntax`,
      `undeclared_reference`, `undefined_field`, `no_matching_overload`, `too_deep`, `source_too_large`, `other`.
      `name` là định danh (với `undeclared_reference`) hay tên trường (với `undefined_field`), `None` với kind khác.
      `message` là chữ của binding, chỉ nói về nguồn.
    - `ExpressionError(code, status)`, với `code` thuộc `expression_error`, `expression_budget_exceeded`, và `status`
      thuộc `INVALID_ARGUMENT`, `NOT_FOUND`, `OUT_OF_RANGE`, `INTERNAL`, `UNKNOWN`, `DEADLINE_EXCEEDED`,
      `RESOURCE_EXHAUSTED`; chữ lỗi của binding không có tiền tố nào trong tập đó thì `status` là `UNKNOWN`. Lỗi không bao
      giờ mang chữ lỗi của binding, vì chữ đó có thể chứa giá trị (đo được: `NOT_FOUND: Key not found in map : "nope"`,
      và chữ ngoại lệ của hàm Python).
    - Protocol `ExpressionEngine` có hai phương thức. `check(source: str, env: ExpressionEnv) -> CheckedExpression |
list[ExpressionIssue]` chạy đồng bộ. `async evaluate(checked: CheckedExpression, activation: Mapping[str, object])
-> object | ExpressionError`. `evaluate` trả giá trị dạng JSON: `dict`, `list`, `str`, `int`, `float`, `bool`,
      `None`; timestamp là chuỗi RFC 3339 có độ lệch, duration là chuỗi dạng `"3600s"`, bytes là base64, và một
      message thành `dict` bỏ trường vắng (dạng JSON của protobuf). Bên gọi cần `bool` mà nhận `None` thì coi là
      `expression_error`, không bao giờ là `false`. Lỗi không mang node hay đường dẫn: bên gọi biết node và tự gắn.
      Kết quả của `check` không có "tham chiếu" hay "ước lượng chi phí": binding không
      lộ hai thứ đó và không ai đọc chúng (ADR-0114 (Accepted) quyết 2, sửa ngày 3/11/2026).
    - Hằng `DW_CEL_LIBRARY = "dw.cel/v1.0"` là giá trị mà tenant-config:R6.1 ghim vào Bản kê lượt chạy (`v1` là bản
      chính; `time.add_workdays` ở W2 thành `dw.cel/v1.1`, ADR-0114 (Accepted) quyết 3). Một `ExpressionEnv` mang
      `library` mà adapter không ship thì là lỗi lập trình, `ValueError`.
    - Thêm `cel_expr_python`, tên import đo từ wheel đã cài, vào `forbidden_modules` của contract "Kernel is pure
      (stdlib only)" (`pyproject.toml:264-288`).
2. `packages/python/dw_studio/src/dw_studio/core/adapters/cel/`, adapter `CelCppEngine`.
    - `check` chạy ngay trong tiến trình gọi (đo được: biên dịch mất khoảng 317 µs).
        - Nguồn trên 2 KiB (2.048 byte UTF-8) trả `source_too_large` mà không biên dịch; đúng 2.048 byte thì được biên
          dịch. Trần này áp cho mọi nguồn qua `check`: điều kiện, biểu thức ánh xạ của từng khóa `data.transform` và
          từng `{{ }}`; trần 16 KiB của cả một Chuỗi có biến là việc của ticket 02.
        - Còn lại, `check` dựng env của binding (bước 3) rồi gọi `env.compile(source)`. Binding báo lỗi biên dịch
          bằng `RuntimeError`; `check` tách nó theo các dòng `<input>:dòng:cột:` thành `ExpressionIssue`, và chọn kind
          theo mẫu chữ đã đo:

            | Mẫu chữ của binding             | kind                   |
            | ------------------------------- | ---------------------- |
            | `Syntax error`                  | `syntax`               |
            | `undeclared reference to '<n>'` | `undeclared_reference` |
            | `undefined field '<f>'`         | `undefined_field`      |
            | `found no matching overload`    | `no_matching_overload` |
            | `Exceeded max recursion depth`  | `too_deep`             |
            | mẫu khác                        | `other`                |

            Mỗi mẫu có một ca trong bộ test hợp đồng. Nhờ vậy, một bản binding đổi chữ sẽ làm test đỏ, thay vì bị xếp
            sai kind một cách lặng lẽ (failure-modes #4).

        - `result_type` là `Expression.return_type()` ánh xạ ngược về đại số kiểu. Một trường wrapper được binding
          kiểm như kiểu vô hướng của nó (đo được: trường `BoolValue` trả `BOOL`), nên ánh xạ về `T`; lúc tính, trường
          vắng ra `None`, và `o.flag && true` với `flag` vắng ra lỗi `UNKNOWN` (đã đo), tức đóng.
    - `evaluate` không tính trong tiến trình gọi, vì binding giữ GIL suốt lúc tính.
        - Nó gửi `(khóa cache, mô tả env, nguồn, activation)` tới một tiến trình tính, trong một pool hai tiến trình
          khởi bằng `multiprocessing` với ngữ cảnh `spawn`. Không dùng `fork`, vì tiến trình gọi có luồng.
        - Việc xếp hàng FIFO chờ một tiến trình rảnh; đồng hồ 1 giây bắt đầu khi tiến trình tính nhận việc, nên thời
          gian xếp hàng và lần khởi tiến trình không tính vào đó. Bên gọi chờ bằng `asyncio`. Quá hạn thì bên gọi giết tiến trình đó, dựng một tiến trình thay,
          và trả `ExpressionError("expression_budget_exceeded", "DEADLINE_EXCEEDED")`. Đo được: khởi tiến trình cộng
          lần tính đầu mất 298 ms; một vòng gửi nhận điển hình 149 µs; một lần tính bệnh hoạn bị giết ở khoảng
          1,07 giây.
        - Trong tiến trình tính, kết quả được xử lý như sau:
            - binding trả một giá trị kiểu `ERROR` → `expression_error`, kèm `status` là tiền tố của chữ lỗi;
            - binding ném `RuntimeError` chứa `Iteration budget exceeded` → `expression_budget_exceeded` (`INTERNAL`);
            - giá trị dạng JSON ở trên, tuần tự hóa, vượt 256 KiB → `expression_budget_exceeded`
              (`RESOURCE_EXHAUSTED`). Khi tuần tự hóa,
              timestamp viết dạng ISO 8601 có múi giờ, duration viết bằng giây, bytes viết base64.
        - Pool được dựng lười ở lần `evaluate` đầu tiên. `aclose()` dừng mọi tiến trình tính. Một tiến trình tính chết
          vì lý do khác thì được dựng lại, và lần tính đó trả `expression_error` (`INTERNAL`). Trên Linux mỗi tiến
          trình tính đặt `RLIMIT_AS` 512 MiB lúc khởi, để một biểu thức dựng chuỗi nhiều trăm MB làm chết tiến trình
          tính chứ không phải tiến trình gọi; Windows không có giới hạn này.
    - Cache chương trình biên dịch là một LRU 10.000 mục ở mỗi tiến trình, cả tiến trình gọi lẫn tiến trình tính.
      Khóa là `(tenant_id, library, env_hash, sha256(source))`; tenant có trong khóa theo CLAUDE.md mục Tenancy and
      authorization (R3.7). Env của binding được cache theo `(tenant_id, library, env_hash)`, trong cùng giới hạn.
    - Activation có một `datetime` không múi giờ thì bị từ chối ở tiến trình gọi, trước khi gửi đi: đó là lỗi lập
      trình, ném `ValueError`. Lý do là binding đọc giờ đó theo giờ của máy (đo được: 01:30 không múi giờ cho
      `getHours()` bằng 18 trên máy UTC+7, và bằng 1 trong container UTC).
3. Kiểu dữ liệu và thư viện trong env của binding:
    - `object{...}` thành một message trong `google.protobuf.descriptor_pool.DescriptorPool` dựng theo env, đặt trong
      gói `dwenv_<12 ký tự đầu của env_hash>`. Kiểu của từng trường như sau:

        | Kiểu trong đại số       | Kiểu proto                                                                          |
        | ----------------------- | ----------------------------------------------------------------------------------- |
        | vô hướng                | wrapper type: `StringValue`, `Int64Value`, `DoubleValue`, `BoolValue`, `BytesValue` |
        | `timestamp`, `duration` | `google.protobuf.Timestamp`, `google.protobuf.Duration`                             |
        | `object` lồng           | message                                                                             |
        | `list[T]`               | `repeated`                                                                          |
        | `map[string, T]`        | `map<string, T>`                                                                    |
        | `dyn`                   | `google.protobuf.Value`                                                             |

        `optional[T]` dùng extension `optional`.

    - Activation dạng dict được chuyển thành message bằng `json_format.ParseDict`, trong tiến trình tính. Khóa lạ thì
      trả `expression_error`. Đo được: chuyển một dict 20 trường rồi tính mất khoảng 267 µs.
    - Trường vô hướng là wrapper, không phải vô hướng proto3. Trường vô hướng proto3 bị vắng đọc thành giá trị không
      (`''`, `0`), nên `x.tier == ''` sẽ đúng với dữ liệu thiếu (failure-modes #7). Wrapper bị vắng đọc thành `null`
      (đã đo).
    - `packages/python/dw_studio/pyproject.toml` khai trực tiếp, ghim chính xác, `cel-expr-python==0.1.3` và
      `protobuf==7.36.1` (bản đang có trong `uv.lock`). `IMPORT_TO_DIST` của `scripts/verify_architecture.py` thêm
      `"cel_expr_python": "cel-expr-python"` và `"google": "protobuf"`.
    - `dw.cel/v1` gồm CEL chuẩn, năm extension `strings`, `math`, `optional`, `encoders`, `bindings` của binding
      (`cel_expr_python.ext`), và các hàm nền tảng dưới đây. Các hàm nền tảng viết bằng Python và đăng ký qua
      `CelExtension`:

        | Hàm                                                   | Hành vi                                                                                                                                           |
        | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
        | `text.nfc(string) -> string`                          | chuẩn hóa Unicode NFC                                                                                                                             |
        | `text.unaccent(string) -> string`                     | NFD, bỏ dấu (nhóm Mn), `đ` thành `d`, `Đ` thành `D`                                                                                               |
        | `text.mask_contacts(string) -> string`                | thay bằng `[đã che]` mỗi địa chỉ email và mỗi dãy giống số điện thoại: dấu `+` tùy chọn, rồi ít nhất 9 chữ số, có thể xen dấu cách, chấm hay gạch |
        | `phone.e164(string) -> string`                        | xem ngay dưới bảng                                                                                                                                |
        | `email.normalize(string) -> string`                   | bỏ khoảng trắng hai đầu và đổi sang chữ thường; không có đúng một `@` thì trả `expression_error`                                                  |
        | `fmt.money_vnd(int) -> string`                        | `1.234.567 ₫`                                                                                                                                     |
        | `fmt.datetime(timestamp) -> string`                   | `dd/MM/yyyy HH:mm` theo `Asia/Ho_Chi_Minh`                                                                                                        |
        | `fmt.date(timestamp)` và `fmt.date(string) -> string` | `dd/MM/yyyy` theo cùng múi giờ; bản `string` nhận ngày dạng `YYYY-MM-DD` (ADR-0114 (Accepted) quyết 4)                                            |

        `phone.e164` bỏ dấu cách, chấm, gạch và ngoặc, rồi xét năm trường hợp:
        - `0` cộng 9 chữ số → `+84` cộng 9 chữ số;
        - `+840` cộng 9 chữ số → `+84` cộng 9 chữ số (bỏ số 0 trung kế);
        - `84` cộng 9 chữ số → `+84` cộng 9 chữ số;
        - `+` cộng 8 đến 15 chữ số, trừ hai trường hợp trên → giữ nguyên;
        - trường hợp khác → `expression_error`, không bao giờ trả chuỗi rỗng.

        `fmt.datetime` và `fmt.date` dùng `zoneinfo` của Python cùng gói `tzdata`, không dùng bảng múi giờ của binding,
        vì binding không tìm được tên múi giờ IANA trên Windows.

        `time.add_workdays` vào cùng lịch làm việc ở W2 (spec, Ngoài phạm vi). Mọi hàm nền tảng báo lỗi bằng cách ném; binding trả
        `ERROR` với `OUT_OF_RANGE` cho mọi hàm Python ném lỗi (đã đo), nên lỗi của mọi hàm nền tảng mang
        `OUT_OF_RANGE`, và adapter trả `expression_error`.
4. Import-linter, hợp đồng của studio-skeleton:R5.6, mà Ngoài phạm vi của studio-skeleton giao cho ticket này:
    - Tên hợp đồng: "CEL binding only in dw_studio.core.adapters.cel". Loại `forbidden`.
    - Nguồn: mọi gói trong `root_packages` (studio-skeleton/02 bước 2 thêm `dw_studio` vào đó).
    - Cấm: `cel_expr_python`.
    - `ignore_imports` cho `dw_studio.core.adapters.cel` và các module con của nó, theo cách ghi `**` mà
      studio-skeleton/02 bước 3 đã đo.
    - `allow_indirect_imports = true`, để một composition root import `CelCppEngine` không bị tính là đã import
      binding.
5. Bộ test hợp đồng ở `packages/python/dw_studio/tests/core/adapters/cel/test_expression_contract.py`, đánh dấu
   `unit`. Bộ test viết theo `ExpressionEngine`, qua một fixture trả về adapter, để một adapter thay thế chạy được
   cùng bộ. Bộ test gồm các nhóm ca sau:
    - Tập con cel-spec: số học, chuỗi, list, map, các macro `all`, `exists`, `exists_one`, `map`, `filter`, hàm
      `has()`, optional, timestamp và duration. Timestamp chỉ dùng độ lệch cố định `'+07:00'`, không dùng tên múi giờ
      IANA trong hàm có sẵn của binding, vì binding chỉ tìm được tên đó trên Linux.
    - Regex RE2: backreference và lookahead bị từ chối; `(a+)+$` trên chuỗi gồm 30 chữ `a` rồi một chữ `b` trả `false`.
    - Mỗi hàm của `dw.cel/v1`, với một ca hợp lệ và một ca lỗi.
    - Mỗi `kind` của `ExpressionIssue` và mỗi `status` đã đo.
    - Các ca ngân sách, đồng hồ và kích thước.
    - `object{...}` có trường vắng, đọc ra `null`.
    - Timestamp không múi giờ bị từ chối.
    - Hai khóa cache của hai tenant khác nhau.

    Vector test của si-platform không có ở đây: chủ của chúng là quy tắc kiểm hợp lệ W2 của custom-objects (hàng tương
    ứng trong Ngoài phạm vi của custom-objects; DO-03.2).

6. Ticket này không gắn engine vào composition root nào, vì chưa có bên nào đọc nó (failure-modes #1). Ticket đầu
   tiên gọi `ExpressionEngine` từ một composition root sẽ dựng ở đó một `CelCppEngine` cho mỗi tiến trình và gọi
   `aclose()` khi tắt: ticket 03 làm việc này cho API (route `/expressions/*`), workflow-engine làm cho worker.
7. `logic.switch@1` của wf-lite (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:378`) chỉ
   tra lane theo một giá trị đã phân giải; nó không tính biểu thức, và ticket này không đổi nó. Khi wf-lite cần một
   điều kiện, nó nhận `ExpressionEngine` qua constructor từ composition root, vì Protocol nằm ở `dw_kernel`. Nó không
   viết một bộ tính thứ hai, và cũng không import được `dw_studio`, vì hợp đồng "Platform core does not import Studio"
   (studio-skeleton/02) cấm điều đó.

## Tiêu chí chấp nhận

- [x] R3.1: với env có `trigger` là `object{amount: int}`, `check("trigger.amount > 1000000", env)` trả một
      `CheckedExpression` kiểu `bool`, và `await evaluate(...)` với `{"trigger": {"amount": 2000000}}` trả `True`.
      Tham chiếu một biến chưa khai → `ExpressionIssue` `undeclared_reference` mang `name` của biến đó, và không có
      lời gọi `evaluate` nào. Biên dịch với `disable_check=True` → test đỏ.
- [x] R3.1: với `score` là `object{response: object{tier: string}}`:
    - `score.response.tierr` → `undefined_field` với `name` `tierr`;
    - `score.response.tier + 1` → `no_matching_overload`;
    - `score.response.tier` với activation thiếu `tier` → `null`;
    - ánh xạ trường vô hướng sang vô hướng proto3 thay cho wrapper → ca `null` đỏ, vì đọc ra `''`.
- [x] R3.1: activation mang `datetime(2026, 11, 3, 1, 30)` không múi giờ → `ValueError` trước khi gửi tới tiến trình
      tính. Gỡ phép kiểm này → test đỏ.
- [x] R3.1: `phone.e164` trả cùng `+84901234567` cho `"0901 234 567"`, `"+84901234567"` và `"+84 0901 234 567"`,
      còn `"12345"` → `expression_error` (`OUT_OF_RANGE`). Đổi nhánh lỗi sang trả `''` → test đỏ.
- [x] R3.1: có các module thử import `cel_expr_python`:
    - một module ngoài `dw_studio.core.adapters.cel` (ở `dw_studio.core.application`, và ở `dw_platform`) →
      `lint-imports` đỏ và nêu tên module đó (studio-skeleton:R5.6);
    - một module trong `dw_kernel` → contract "Kernel is pure" đỏ;
    - gỡ hợp đồng, hay bỏ `cel_expr_python` khỏi denylist → module thử qua, test đỏ.
- [x] R3.4 (WN12): `xs.map(a, xs.map(b, xs.map(c, a+b+c)))` với `xs` 22 phần tử → `expression_budget_exceeded`;
      21 phần tử → trả giá trị. Ánh xạ lỗi ngân sách của binding sang `expression_error` → test đỏ.
- [x] R3.4 (WN12): đo sau một lần tính làm ấm. Biểu thức 77 byte nối 19 lần một list 500 phần tử rồi `.map(a, a+1)`
      (đo được 5,6 giây khi tính trong tiến trình) → `expression_budget_exceeded` trong ≤ 1,5 giây. Trong thời gian
      đó, một tác vụ asyncio của bên gọi đếm nhịp 10 ms đếm được ít nhất 50 nhịp, và lần `evaluate` kế tiếp trả đúng
      giá trị. Gỡ đồng hồ, hay tính ngay trong tiến trình gọi → test đỏ, vì lâu hơn 1,5 giây hoặc thiếu nhịp.
- [x] R3.4 (WN12): `s + s + s` với `s` 100 KiB (kết quả 300 KiB) → `expression_budget_exceeded`; `s + s` (200 KiB) →
      trả giá trị. Gỡ trần 256 KiB → test đỏ.
- [x] R3.7 (WN36): cùng nguồn và cùng biến cho tenant A và tenant B → cache có hai mục. Bỏ `tenant_id` khỏi khóa →
      còn một mục, test đỏ.
- [x] R3.1: `uv.lock` ghim chính xác `cel-expr-python==0.1.3` và `protobuf==7.36.1`, và không có
      `common-expression-language`. `scripts/verify_architecture.py` xanh khi `dw_studio` import `cel_expr_python` và
      `google.protobuf`.
- [x] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:168`; spec: R3.1 (chỗ `str.format` phải
  tránh cho văn bản tenant).
- `pyproject.toml:264-288`; spec: R3.1 (denylist kernel).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:378`; spec: R3.1 (switch của wf-lite là
  phép tra, không phải bộ tính).
- studio-skeleton:R5.6 (chỉ `dw_studio.core.adapters.cel` import thư viện CEL); spec: R3.1, Trong phạm vi.
- ADR-0114 (Accepted) quyết 2-4 và Amendments 2026-11-03 (số đo FOG-50); spec: R3.

## Comments

- 2026-10-23 (agent): DO-38 còn mở — Đạt chốt binding mặc định sau nhánh thử (FOG-50); đến lúc đó giữ
  needs-info.
- 2026-10-23 (agent): DO-38 đã có lời đáp (Đạt 23/10/2026: C++ mặc định, Rust dự phòng, nếu số đo FOG-50 giữ được), nên ticket về `needs-triage`; luật chọn sau nhánh thử ở bước 1. DO-03.2 và DO-37 cũng đã có lời đáp; route theo dạng sub-resource của ADR-0108 (Accepted).
- 2026-10-24 (agent): vòng sửa thứ tư, V4.P13 (agent, tạm), sửa ở lượt b để khớp ADR-0114 (Accepted) quyết 2: ticket ship cả `CelCppEngine` và `CelRustEngine` qua một bộ test hợp đồng, composition root chọn theo setting; ở profile triển khai (`settings.is_deployed`) setting phải chọn `cel-expr-python` và một test đỏ khi nó trỏ sang bản Rust (R3.6, WN19); chuyển profile triển khai sang bản Rust thì sửa CLAUDE.md mục Required stack trong cùng thay đổi. Bản lượt a của dòng này (chỉ ship `cel-expr-python`, không setting) trái quyết định đó (phát hiện E về CLAUDE.md mục Required stack và ticket này).
- 2026-10-24 (agent): lượt c của vòng 4: hai adapter ở `dw_studio.core.adapters.cel`, gói mà studio-skeleton:R5.6 chỉ cho import thư viện CEL, và ticket này viết hợp đồng import-linter đó, kèm tiêu chí R3.1 thấy `lint-imports` đỏ (studio-skeleton:R5.6); dòng `Xong:` đổi sang `make ci`, vì `make test-architecture` của nó chạy `lint-imports` (`Makefile`, đích `test-architecture`), và bộ test hợp đồng dời theo gói sang `tests/core/adapters/cel/`, đánh dấu `unit` để `make test-unit` chạy nó (bước 4).
- 2026-10-24 (agent): lượt d của vòng 4: hai dòng Comments của lượt b, c thôi dẫn mã mục của lượt, nội dung giữ nguyên.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check; không có route hay
  migration).
    - FOG-50 được đo thật, trong venv tạm trên Windows và trong ảnh `python:3.12-slim-bookworm`; số đo ở ADR-0114 (Accepted),
      Amendments 2026-11-03.
    - Lượt đầu CHƯA ĐẠT, 1 CRITICAL và 8 HIGH, đều đã sửa:
        - CRITICAL: khóa cache thiếu tenant (CLAUDE.md mục Tenancy and authorization), nay là R3.7 và WN36.
        - Bản Rust không có bộ kiểm kiểu, AST hay ngân sách: map lồng 1.000 × 1.000 chạy 107 giây. Bản Rust bị bỏ,
          cùng R3.6 và WN19.
        - Ngân sách 10.000 vòng cố định trong binding, và `map`/`filter` tốn thời gian bậc hai trong lúc giữ GIL: một
          biểu thức 77 byte giữ tiến trình 5,6 giây, đường `split` giữ 6,4-7,5 giây. Thêm tiến trình tính riêng với
          đồng hồ 1 giây (R3.4, WN12); phép đột biến cũ "gỡ ngân sách ở `CelCppEngine`" không làm được.
        - Hai route của R3.5 không có bước nào dựng: chuyển sang ticket 03.
        - Kiểu đối tượng cần descriptor protobuf, và trường vô hướng proto3 bị vắng đọc thành `''`: dùng wrapper.
        - Thư viện `dw.cel/v1` không có chủ: ticket này nhận, với hành vi của từng hàm.
        - Vector si-platform có hai chủ: custom-objects W2 giữ.
        - `check` hứa tham chiếu và ước lượng chi phí mà binding không có: bỏ.
        - Setting và worker không có bên đọc: không gắn vào composition root nào.
- 2026-11-03 (agent): MEDIUM của gate, cho người làm:
    - (a) Hàng R5.6 trong Ngoài phạm vi của studio-skeleton và dòng Quyết định 24/10/2026 của spec đó vẫn nói hợp đồng
      nêu hai binding. Bản thân R5.6 vẫn đúng. Không sửa ở đây, vì sửa Ngoài phạm vi sẽ đặt lại ĐẠT của spec đó; để
      `checking-plan-consistency` của area gióng lại.
    - (b) Wheel thêm khoảng 66 MB vào ảnh, trong đó 16 MB là cây build `bazel-project` thừa (bản Windows có 2.339 tệp
      `bazel-cel-python-build-290`). `reviewing-deployment-security` ở lúc đóng hàng đợi xem phần này, cùng nhiễu của
      trivy.
    - (c) Không có sdist, nên nền tảng không có wheel (musl) không cài được.
    - (d) Một biểu thức 2 KiB dựng được chuỗi nhiều MB trước khi tới trần 256 KiB (đo được: nối 8 MB mất 23 ms). Trên
      Linux nên đặt `RLIMIT_AS`, ví dụ 512 MiB, cho tiến trình tính.
    - (e) Regex sai trong literal chỉ lộ ra lúc tính; ticket 03 có thể kiểm trước.
    - (f) Một node tính nhiều biểu thức trên cùng activation thì chuyển dict sang message một lần.
    - (g) Đo latency ở lúc đóng hàng đợi nhớ cộng 149 µs cho mỗi vòng gửi nhận.
    - (h) Câu hỏi B7 của builder check không còn áp dụng, vì đã bỏ luật chọn binding. Câu B8 đã có lời đáp: có wheel
      `win_amd64` cp312.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 9 câu và 2 tình huống, sửa theo
  khuyến nghị: đồng hồ tính từ lúc tiến trình tính nhận việc, hàng FIFO; `evaluate` trả dạng JSON, `None` không bao
  giờ là `false`; trường wrapper kiểm như `T`; lỗi của hàm nền tảng là `OUT_OF_RANGE` như binding trả (đo), kích thước
  là `RESOURCE_EXHAUSTED`; `DW_CEL_LIBRARY` mang bản phụ `dw.cel/v1.0`; trần 2 KiB cho mọi nguồn qua `check`;
  `RLIMIT_AS` 512 MiB trên Linux; lỗi không mang node, bên gọi gắn; `phone.e164` bỏ số 0 trung kế sau `+84`.
  MEDIUM: `dyn` qua `google.protobuf.Value` giữ số dạng double, nên số nguyên trên 2^53 trong trường json mất chính
  xác; trường có kiểu `int` dùng `Int64Value` nên không bị. tenant-config:R6.1 viết "`dw.cel/v1`", đọc là bản chính
  của `dw.cel/v1.0`; `checking-plan-consistency` gióng lại.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent): Xong, `73ee226` (mã) và commit test ngay sau. Mọi tiêu chí xanh trên Windows và trong
  `python:3.12-slim-bookworm`; dòng `Xong` đọc theo wave-close.md: ruff, format, mypy, lint-imports, bandit,
  verify_architecture, test_verify_architecture.sh, verify_invariants, check_hygiene, pip-audit (không lỗ hổng),
  unit của `dw_kernel` và `dw_studio` với `-n auto`. Mười bảy đột biến của `mutations/01.yaml` đã thấy đỏ bằng tay, tại
  chỗ (bản Linux trong container), vì bộ test qua ngay lần đầu; `scripts/mutate.py` chạy ở lúc đóng hàng đợi.
- 2026-11-04 (agent): Khác với ticket, đều đo trên binding trước khi dựa vào:
    - Trên Linux, biểu thức 77 byte của WN12 lên tới 1,7 GB khi không giới hạn, nên `RLIMIT_AS` 512 MiB dừng nó ở
      khoảng 0,8 giây bằng `MemoryError` (std::bad_alloc), trước đồng hồ. Test của tiêu chí đó nhận
      `expression_budget_exceeded` với `DEADLINE_EXCEEDED` (Windows) hoặc `RESOURCE_EXHAUSTED` (Linux). Đồng hồ có
      thêm một test riêng đỏ trên cả hai nền: 9.801 lần quét regex trên 300 KB (5 giây khi tính trong tiến trình,
      đỉnh 32 MB) phải ra `DEADLINE_EXCEEDED`.
    - Nhịp 10 ms đếm theo ô 10 ms mà tác vụ của bên gọi chạy được (`sleep(0)`), vì Windows làm tròn `sleep(0.01)`
      lên 15,6 ms: dưới `-n auto` chỉ đếm được 47 nhịp dù vòng sự kiện rảnh.
    - Binding cắt `str` và `bytes` truyền thẳng ở U+0000 (`'a�b'` đọc ra `'a'`), còn trong message thì giữ nguyên;
      chuỗi truyền thẳng có U+0000 trả `expression_error` (`INVALID_ARGUMENT`).
    - Binding không khai được biến cấp cao kiểu optional (không có chữ ký `optional_type` nào nó nhận). Biến cấp cao
      `optional[T]` khai như `T`, vắng thì bỏ khỏi activation, đọc tới thì đóng (`UNKNOWN`). Trường `optional[T]`
      dùng cùng trường wrapper hay message như `T`, kiểm bằng `has()` và `.?f` (ADR-0112 (Accepted), Amendments 2026-11-04).
    - Kết quả không có dạng JSON (optional, kiểu) bị từ chối ở `check` với `other`, không chờ tới lúc tính. Double
      không hữu hạn và khóa activation không khai ở cấp cao trả `expression_error` (`INVALID_ARGUMENT`).
    - Mẫu chữ thứ hai của `too_deep` (`CANCELLED: Expression recursion limit exceeded`, không có vị trí) cũng được
      xếp vào `too_deep`.
    - `tzdata>=2024.1` thành phụ thuộc chạy của `dw-studio`. mypy đọc stub `.pyi` của binding
      (`follow_untyped_imports`) và bỏ qua kiểu của `google.protobuf`.
    - Hai hợp đồng import-linter được thử bằng `tests/unit/test_cel_import_contracts.py`: chạy đúng hai hợp đồng đọc từ
      `pyproject.toml` trên một cây gói rỗng có cắm một module thử.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `MemoryError` trong tiến trình tính trả `expression_budget_exceeded`
  (`RESOURCE_EXHAUSTED`), không phải `expression_error` (`INTERNAL`): tiến trình không chết, và đó là một trần tài nguyên
  như trần 256 KiB. Nếu sai thì: một nhánh trong `evaluator.evaluate`, và tiêu chí 77 byte trên Linux đổi theo.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): message thành JSON với số nguyên giữ là số, không thành chuỗi như dạng
  JSON chuẩn của protobuf cho `int64`; trường vắng bị bỏ như ticket nói. Nếu sai thì: `schema._message_json` gọi
  `json_format.MessageToDict`, và bên đọc nhận `"2000000"`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): list hay map lồng trong trường của `object{...}` (`list[list[T]]`,
  map của list...) không có dạng proto, nên dựng env ném `ValueError`; ở cấp cao thì được. Nếu sai thì: sinh một
  message bọc cho mỗi container lồng, và đường dẫn CEL đổi theo.
- 2026-11-04 (agent): MEDIUM, cho ticket sau:
    - (a) Binding cũng cắt chuỗi ở U+0000 khi gọi hàm Python và khi nhận kết quả của nó, nên `text.mask_contacts`
      và các hàm nền tảng khác chỉ thấy phần trước U+0000 của một chuỗi lấy từ message. Chặn U+0000 ở mọi chuỗi đi vào
      (cả trong message) là một lựa chọn; ticket 03 quyết khi dựng env từ schema.
    - (b) Ticket 03 và tools-and-skills ánh xạ schema có mảng lồng sẽ gặp `ValueError` ở trên.
    - (c) Đo được trong smoke: lần `evaluate` đầu (khởi tiến trình) 0,22 giây trên Windows, 0,5 giây trong container;
      một vòng gửi nhận khoảng 1,4 ms trên Windows. Đo latency ở lúc đóng hàng đợi cộng phần này cho route
      `/expressions/evaluate` của ticket 03.
- 2026-11-04 (agent): Còn nợ ở lúc đóng hàng đợi: `scripts/mutate.py .claude/plans/studio/workflow-nodes/mutations/01.yaml`
  (một mục `runner: linux`); latency không có gì để đo ở ticket này vì chưa có route hay trang nào gọi engine.
