# 01 — Thử nghiệm CEL rồi cổng ExpressionEngine, hai bộ điều hợp và bộ test hợp đồng

Status: needs-triage
Blocked by: .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md
Area: studio
Yêu cầu: R3.1, R3.4, R3.5, R3.6, WN12, WN19

## Mục tiêu

Dựng nền biểu thức của Studio: một cổng `ExpressionEngine` thuần stdlib ở `dw_kernel` và hai bộ điều hợp CEL ở
`dw_studio`, `CelCppEngine` trên `cel-expr-python` và `CelRustEngine` trên `common-expression-language`, qua một bộ
test hợp đồng, có trần chi phí và kích thước; composition root chọn một bộ theo setting như ADR-0114 (Accepted) quyết
2, và profile triển khai luôn chọn `cel-expr-python`, thư viện CLAUDE.md mục Required stack ghim (workflow-nodes R3.1,
R3.4, R3.5, R3.6, WN12, WN19). Trước cổng là một nhánh thử chứng minh thư viện làm được điều cần (DO-38).

## Việc cần làm

1. Nhánh thử (số đo vào ADR-0114 (Accepted), script không vào repo; đây là phép đo FOG-50 của discovery/16,
   ticket khám phá đóng bằng một dòng trỏ tới số đo ở đây): venv tạm với `cel-expr-python==0.1.3` và
   `common-expression-language==0.10.0`. Đo sáu câu: đăng ký được hàm Python (`phone.e164`,
   `time.add_workdays`) không; khai được kiểu đối tượng có trường để kiểm `score.response.tier` tĩnh
   (không `map(string, dyn)`) không; ngân sách với map 200 phần tử × 3 trường; wheel manylinux hợp ảnh
   Python 3.12 của repo; `matches` dùng RE2; thời gian một điều kiện điển hình. Ghi tên module import thật
   của hai binding. Luật chọn (DO-38, V4.P13; ADR-0114 (Accepted) quyết 2): bản C++ đạt thì là mặc định và là giá
   trị của setting ở profile triển khai; bản C++ không đăng ký được hàm Python hay kiểu đối tượng có trường thì
   `CelRustEngine` thành mặc định cùng tiền-kiểm AST, và chuyển profile triển khai sang nó sửa CLAUDE.md mục Required
   stack trong cùng thay đổi; cả hai trượt thì dừng ticket và báo Đạt.
2. `packages/python/dw_kernel/src/dw_kernel/expressions.py`: Protocol `ExpressionEngine` với
   `check(source, env)` trả biểu thức đã kiểm (kiểu, tham chiếu, ước lượng chi phí) hoặc danh sách lỗi,
   và `evaluate(checked, activation)`; đại số kiểu đóng (`null`, `bool`, `int`, `double`, `string`,
   `bytes`, `timestamp`, `duration`, `list[T]`, `map[string, T]`, `object{...}`, `optional[T]`, `dyn`);
   mã lỗi. Thêm tên module import thật của hai binding, đo ở bước 1 chứ không đoán (failure-modes #4), vào
   denylist contract "Kernel is pure (stdlib only)" (`pyproject.toml:252-254`) để guard thấy được chúng.
3. `packages/python/dw_studio/src/dw_studio/adapters/expressions/`: `CelCppEngine` trên
   `cel-expr-python==0.1.3` (mặc định) và `CelRustEngine` trên `common-expression-language==0.10.0` sau một tiền-kiểm
   AST (độ lồng comprehension tối đa 2, literal list tối đa 1.000 phần tử), cả hai ghim chính xác trong
   `pyproject.toml` và `uv.lock`. Composition root của API và worker chọn một bộ bằng setting (V4.P13); khi
   `settings.is_deployed`, setting phải chọn `cel-expr-python` và giá trị trỏ sang bản Rust bị từ chối, nên một test
   đỏ khi setting của profile triển khai trỏ sang `CelRustEngine` (R3.6, CLAUDE.md mục Environments); chuyển profile
   triển khai sang bản Rust thì sửa CLAUDE.md mục Required stack trong cùng thay đổi. `evaluate` áp ngân sách vòng
   khoảng 10.000 và trần 256 KiB cho kết quả tuần tự hóa (ADR-0114 (Accepted) quyết 4). Import-linter: chỉ adapter
   import thư viện CEL.
4. Bộ test hợp đồng chạy cho cả hai adapter (ADR-0114 (Accepted) quyết 2): tập con cel-spec, thư viện hàm, ca ngân
   sách và kích thước, vector test `rules.py` của si-platform (D5) port theo thỏa thuận viết với chủ mã (DO-03.2: ghim
   commit, dòng đầu `Ported from si-platform`, không đồng bộ; chưa có thỏa thuận trước P1 thì viết lại theo
   cùng vector), mỗi vector kiểm cực tính theo ADR-0114 (Accepted) quyết 6 vì Điều kiện để lưu được nghĩa là
   "phải đúng" (DO-37). Cache chương trình biên dịch theo
   `(phiên bản thư viện, mã băm env, sha256(source))` trong LRU giới hạn 10.000.

## Tiêu chí chấp nhận

- [ ] R3.1: một Biểu thức đi qua `ExpressionEngine.evaluate`, không có đường nào gọi `str.format`,
      `jinja2` hay `eval` trên nguồn của công ty; biến chưa khai → lỗi biên dịch khi `check`.
- [ ] R3.4 (WN12): map lồng 3 cấp trên 22 phần tử → `expression_budget_exceeded` trong < 50 ms ở cả hai adapter; gỡ
      ngân sách vòng ở `CelCppEngine`, hay tiền-kiểm AST ở `CelRustEngine` → ca đó chạy hết, treo hoặc không trả lỗi
      (test đỏ).
- [ ] R3.5: `/expressions/check` và `/expressions/evaluate` chạy ở máy chủ; bundle web không chứa thư viện
      CEL (kiểm ở workflow-builder-ui ticket 03).
- [ ] R3.6 (WN19): khi `settings.is_deployed`, composition root của API và worker dựng `CelCppEngine`; setting chọn
      `CelRustEngine` khi `settings.is_deployed` → bị từ chối, và test của setting ở profile triển khai đỏ khi giá trị
      trỏ sang bản Rust; ngoài profile triển khai, setting chọn `CelRustEngine` thì composition root dựng nó.
- [ ] WN12: cùng một bộ test hợp đồng xanh cho cả `CelCppEngine` và `CelRustEngine`; `uv.lock` ghim chính xác
      `cel-expr-python==0.1.3` và `common-expression-language==0.10.0`.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/adapters/test_expression_contract.py` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:168`; spec: R3.1 (chỗ
  `str.format` phải tránh cho văn bản tenant).
- `pyproject.toml:252-254`; spec: R3.1 (denylist kernel).
- ADR-0114 (Accepted), ADR-0112 (Accepted); spec: R3.
- si-platform `rules.py` (D5, trích theo repo + tên file); spec: R3.

## Comments

- 2026-10-23 (agent): DO-38 còn mở — Đạt chốt binding mặc định sau nhánh thử (FOG-50); đến lúc đó giữ
  needs-info.
- 2026-10-23 (agent): DO-38 đã có lời đáp (Đạt 23/10/2026: C++ mặc định, Rust dự phòng, nếu số đo FOG-50 giữ được), nên ticket về `needs-triage`; luật chọn sau nhánh thử ở bước 1. DO-03.2 và DO-37 cũng đã có lời đáp; route theo dạng sub-resource của ADR-0108 (Accepted).
- 2026-10-24 (agent): vòng sửa thứ tư, V4.P13 (agent, tạm), sửa ở lượt b (B1) để khớp ADR-0114 (Accepted) quyết 2: ticket ship cả `CelCppEngine` và `CelRustEngine` qua một bộ test hợp đồng, composition root chọn theo setting; ở profile triển khai (`settings.is_deployed`) setting phải chọn `cel-expr-python` và một test đỏ khi nó trỏ sang bản Rust (R3.6, WN19); chuyển profile triển khai sang bản Rust thì sửa CLAUDE.md mục Required stack trong cùng thay đổi. Bản lượt a của dòng này (chỉ ship `cel-expr-python`, không setting) trái quyết định đó (phát hiện E về CLAUDE.md mục Required stack và ticket này).
