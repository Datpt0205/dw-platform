# 03 — Phạm vi biến, kiểm kiểu khi gửi kiểm định và các bước logic

Status: needs-triage
Blocked by: 02, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/usage-and-limits/issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md
Area: studio
Yêu cầu: R2.3, R2.4, R3.2, R3.3, R3.5, R4.4, WN5, WN11

## Mục tiêu

Mỗi Biểu thức kiểm kiểu tại vị trí bước, chỉ tham chiếu bước trội, và từ chối Trường người chạy không
đọc được; người dựng kiểm và tính thử Biểu thức chỉ ở máy chủ; ba bước logic lát cần với mặc định đóng
(workflow-nodes R2.3, R2.4, R3.2, R3.3, R3.5, R4.4, WN5, WN11).

## Việc cần làm

1. Môi trường biểu thức theo vị trí: `trigger`; mọi bước trội vị trí đó (dùng chung hàm dominator của
   `workflow-engine`, không bản sao); `bindings` (chỉ biến, không id kết nối); `run` (`id`, `mode`,
   `started_at`, `workflow`); `item`/`index` trong thân map. Không `now()`.
2. `GET /api/v1/studio/workflows/{id}/draft/scope?node=` (quyền `studio.workflows.edit`): cây biến có
   kiểu chỉ gồm bước trội, Trường đọc được với chủ thể chạy (dùng `visible_fields` của field-security).
3. Bộ kiểm khi gửi kiểm định (đưa vào bộ kiểm khi gửi kiểm định của workflow-engine, chạy trên `WorkflowIR` dẫn
   từ cây Bước, mã theo bảng `wf.*` của workflow-engine:R2, tên theo ADR-0112 (Accepted) quyết 3): tham chiếu chưa
   khai hoặc không trội →
   `wf.ref_not_dominating`; điều kiện không `bool` → `wf.type_mismatch`; Trường người chạy không
   đọc được → `field_not_readable`; bảng ánh xạ kiểu dùng chung, keyed theo kiểu trường của
   custom-objects.
4. Ba loại bước: `data.transform` (tối đa 50 khoá), `logic.switch` (mỗi nhánh một Nhánh ra mang một làn Bước, làn
   mặc định "Khác" bắt buộc, các làn gộp lại dưới Bước; cạnh có điều kiện tới mỗi làn do trình biên dịch của
   workflow-engine dựng, V4.24), `flow.stop`; theo ba tính chất vị trí bắt buộc của ticket 02, `flow.stop@1` khai
   `ends_run` đúng, và mọi loại của ticket này khai `opens_wait`, `exits_loop` sai (`data.transform@1` và
   `logic.switch@1` khai cả `ends_run` sai). Hình chiếu `trigger.endpoint` ánh xạ payload vào `input_schema`
   bằng CEL, đánh giá ở ingress.
5. Mặc định đóng: một bước không khai Khi lỗi → `fail`; một `logic.switch` thiếu Nhánh ra mặc định →
   `wf.router_not_total`, không niêm phong.
6. `POST /api/v1/studio/expressions/check` và `POST /api/v1/studio/expressions/evaluate` theo mục API của spec (dạng
   sub-resource của ADR-0108 (Accepted); quyền `studio.workflows.edit`; giới hạn tần suất theo người qua
   `RateLimiterPort` của usage-and-limits/05): kiểm hoặc tính một Biểu thức trong môi trường của bước 1 tại một node,
   với mẫu người gọi gõ hoặc đầu ra bước đã ghi mà người gọi đọc được, đã che (`platform.run_steps` của
   telemetry-and-audit/03); mã lỗi theo mục API. Ticket này là bên đọc đầu tiên của `ExpressionEngine` ở API, nên dựng
   một `CelCppEngine` trong `build_studio` (studio-skeleton/02 bước 5) và gọi `aclose()` khi API tắt (ticket 01 bước 6).

## Tiêu chí chấp nhận

- [ ] R3.2: một Biểu thức tham chiếu một bước phía sau (không trội) → `wf.ref_not_dominating`, không
      niêm phong.
- [ ] R3.3: một điều kiện trả `string` → `wf.type_mismatch`, không niêm phong.
- [ ] R4.4 (WN5): tham chiếu `phone` không đọc được với chủ thể chạy → `field_not_readable` lúc gửi kiểm
      định và `field_hidden` lúc render; gỡ kiểm `visible_fields` → test đỏ.
- [ ] R2.3 (WN11): một bước không khai Khi lỗi biên dịch ra `fail`, không `continue`.
- [ ] R2.4 (WN11): một `logic.switch` thiếu Nhánh ra mặc định → `wf.router_not_total`, không niêm phong;
      thêm nhánh mặc định → qua.
- [ ] R3.2: cây `draft/scope` của một node chỉ liệt kê bước trội; bước phía sau không xuất hiện.
- [ ] R3.5: `POST /api/v1/studio/expressions/evaluate` với `trigger.amount > 10` và mẫu `{"trigger": {"amount": 11}}` trả
      `true` từ máy chủ; người gọi không giữ `studio.workflows.edit` → 403, người của công ty khác gọi trên quy trình
      này → 404; gỡ kiểm quyền → test đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_variable_scope.py packages/python/dw_studio/tests/workflows/test_logic_nodes.py` xanh.

## Nguồn

- ADR-0114 (Accepted) quyết 3, 6; spec: R3.2, R3.3, R4.4.
- ADR-0112 (Accepted) quyết 3; spec: R2.4 (bộ kiểm khi gửi kiểm định).

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: mã của các kiểm này là bảng `wf.*` của workflow-engine:R2 (phát hiện A về hai bảng mã); "phát hành" đổi thành "gửi kiểm định" cho bước niêm phong theo bảng thuật ngữ.
- 2026-10-24 (agent): vòng sửa thứ tư: hai mã đổi theo ADR-0112 (Accepted) quyết 3, `wf.ref_not_dominating` và `wf.type_mismatch` (phát hiện CRITICAL F về ADR-0112 (Accepted) và workflow-engine:R2).
- 2026-10-24 (agent): theo V4.24 của Đạt: tài liệu là cây Bước, nên `logic.switch` mang mỗi nhánh thành một làn Bước với làn mặc định "Khác", không còn Đường nối lưu trong tài liệu, và bộ kiểm chạy trên `WorkflowIR` dẫn từ cây. Ba loại điều khiển của bậc B (V4.26) vào ticket 07, không vào ticket này, để workflow-nodes/04, 05, 06, mà marketing-pilot/03 chờ, không chờ bậc B. Không thêm cạnh.
- 2026-10-25 (agent): `flow.stop@1` khai `ends_run` đúng và hai loại kia khai cả ba tính chất vị trí sai, theo trường bắt buộc của ticket 02 (dòng Quyết định 25/10/2026 của spec); phép hạ của workflow-engine/01 đọc `ends_run` để biết Bước nào không có cạnh ra. Không thêm cạnh.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): nhận R3.5 và hai route `/expressions/check`, `/expressions/evaluate` từ
  ticket 01 (gate của ticket 01): không ticket nào dựng chúng, mà route cần môi trường theo vị trí và `draft/scope` của
  ticket này, `studio.workflows.edit` của workflow-engine/01, `RateLimiterPort` và lịch sử chạy; thêm hai chặn tương
  ứng. workflow-builder-ui/03 đã chờ ticket này cho `/expressions/check`. Gate của ticket này kiểm lại phần đó; dòng
  `Xong:` cần thêm test của hai route.
