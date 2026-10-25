# 02 — Sổ đăng ký loại bước, API danh mục và bộ dựng mẫu {{ }} theo đích

Status: needs-triage
Blocked by: 01, .claude/plans/studio/tools-and-skills/issues/01-executor-kiem-schema-va-nha-may.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.4, R1.5, R4.1, R4.2, R4.3, WN1, WN2, WN13, WN15

## Mục tiêu

Một `NodeTypeRegistry` là nguồn duy nhất cho bảng bước, bộ kiểm, trình biên dịch và phân tích bộ ba, với
API danh mục và bộ dựng Chuỗi có biến `{{ }}` render theo sáu đích, prompt bao chứa (workflow-nodes R1.1,
R1.2, R1.4, R1.5, R4.1, R4.2, R4.3). Kiểm `type@major` chưa đăng ký là `wf.unknown_node_type` của
workflow-engine/01, đọc tập loại từ registry của ticket này.

## Việc cần làm

1. `packages/python/dw_studio/src/dw_studio/workflows/node_registry.py`: `NodeTypeSpec` (type@major,
   schema cấu hình, schema đầu ra, Nhánh ra, mỗi Nhánh ra là một làn Bước lồng trong Bước của tài liệu dạng cây
   (V4.24), Mức tác động `SideEffectLevel`, nhãn năng lực, chính sách Khi lỗi cho phép, giới hạn, quyền và quyền
   lợi, hành vi theo Chế độ chạy, bộ trích phụ thuộc, hook biên dịch, và ba tính chất vị trí `opens_wait`,
   `ends_run`, `exits_loop`: mở điểm chờ, kết thúc lượt chạy, thoát vòng lặp) và `build_node_registry(ports)` gọi ở
   cả hai composition root. Ba tính chất vị trí là trường bắt buộc không có giá trị mặc định: mỗi ticket đăng ký một
   loại khai cả ba cho loại đó, và một mục thiếu một tính chất thì registry không dựng được, để một loại chờ mới của
   W2 không lọt kiểm của làn song song vì một mặc định sai (failure-modes #7). Bảng "thuộc tính → nơi đọc" có test;
   nơi đọc ba tính chất là bộ kiểm của workflow-engine (phép hạ `lower` không nối cạnh ra khỏi một Bước `ends_run`
   và nối lối ra của vòng lặp cho một Bước `exits_loop`, workflow-engine/01; kiểm của workflow-engine:R2.15-R2.17,
   workflow-engine/06).
2. Schema đầu ra mỗi loại công bố đối tượng có tên và kiểu; `error` chỉ có khi Khi lỗi là `continue` hay `route`,
   để Bước kế tiếp (`continue`) và các Bước của làn lỗi (`route`) đọc được lỗi (R1.5, mẫu học từ config-chang.md
   mẫu 2).
3. Route `GET /api/v1/studio/node-types` (quyền `studio.workflows.edit`): trả cấu hình, đầu ra, Nhánh
   ra, nhãn tiếng Việt, giới hạn đã kẹp theo gói, nhãn năng lực, Mức tác động và lý do bị khoá cho người
   gọi. Băm danh mục của API bằng băm worker dựng.
4. `packages/python/dw_studio/src/dw_studio/workflows/templates.py`: tokenizer nhận biết CEL; sáu đích
   `prompt`, `text`, `html`, `url`, `header`, `json`. Đích `prompt` gọi `contain_untrusted` cho mỗi giá
   trị và cắt 16 KiB. Giới hạn: tối đa 50 Biểu thức một mẫu, 64 KiB một mẫu. Host của URL không bao giờ
   là Biểu thức.
5. Test kiến trúc trong `dw_studio`: cấm `jinja2` và `.format(` trên giá trị; `list` trong đích `text`
   → `non_scalar_in_text`; header có CRLF → lỗi lúc chạy.

## Tiêu chí chấp nhận

- [ ] R1.1: băm danh mục của `GET /api/v1/studio/node-types` bằng băm của danh mục worker dựng.
- [ ] R1.2: danh mục trả đủ schema cấu hình, đầu ra, Nhánh ra, nhãn, Mức tác động, giới hạn và lý do
      khoá cho mỗi loại.
- [ ] R1.4 (WN15): thêm một thuộc tính vào `NodeTypeSpec` mà không có nơi đọc → test bảng
      thuộc-tính-tới-nơi-đọc đỏ; một mục bỏ trống `opens_wait`, `ends_run` hay `exits_loop` → `build_node_registry`
      lỗi, không giá trị mặc định nào thay; cho ba trường một mặc định `False` → mục thiếu dựng được, test đỏ.
- [ ] R1.5: một loại có `error` trong schema đầu ra chỉ khi Khi lỗi `continue` hay `route`; một Bước khai `route`
      có `error` mà các Bước của làn lỗi tham chiếu được; loại mặc định `fail` không công bố `error`.
- [ ] R4.1: cùng một giá trị render khác nhau theo đích `text` và `html` (thoát HTML ở `html`).
- [ ] R4.2 (WN2): một lời nhắn lead chứa `</input>` render ở đích `prompt` không đóng được khối; gỡ
      `contain_untrusted` ở đích prompt → test đỏ.
- [ ] R4.3 (WN13): `https://{{ trigger.input.host }}/` ở đích `url` → `templated_host`, không render.
- [ ] WN1: mẫu `{0}{x.__class__}` render ra nguyên văn; gỡ tokenizer nhận biết CEL → test kiến trúc đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_node_registry.py packages/python/dw_studio/tests/workflows/test_templates.py` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:19`; spec: R1.2 (Mức tác động).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`; spec: R4.2
  (`contain_untrusted`).
- ADR-0112 (Accepted) quyết 2; spec: R1, R4.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026, R1.3 rút: kiểm `type@major` chưa đăng ký là hàng `wf.unknown_node_type` của bảng mã workflow-engine:R2.14, làm ở workflow-engine/01.
- 2026-10-24 (agent): theo V4.24 và V4.26 của Đạt: Nhánh ra của mỗi loại là một làn Bước của tài liệu dạng cây, và `on_error: route` vào W1, nên `error` có dưới cả `continue` lẫn `route` (R1.5). Ba loại điều khiển của bậc B và ba tính chất vị trí của `NodeTypeSpec` là của ticket 07. Không thêm cạnh.
- 2026-10-25 (agent): ba tính chất vị trí của `NodeTypeSpec` chuyển từ ticket 07 về ticket này, thành trường bắt buộc không mặc định, vì bộ kiểm của workflow-engine/06 đọc chúng mà ticket 07 chờ ticket đó, và một mặc định sai là mặc định mở cho một loại chờ mới (failure-modes #7); ticket 03 khai `ends_run` của `flow.stop@1`, ticket 06 `opens_wait` của `human.approval@1`, ticket 07 `exits_loop` của `logic.break@1` (dòng Quyết định 25/10/2026 của spec, agent, tạm). Không thêm cạnh: ticket này đã là tổ tiên của workflow-engine/01 và 06.
