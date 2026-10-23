# 03 — Phạm vi biến, kiểm kiểu khi phát hành và các bước logic

Status: needs-triage
Blocked by: 02, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md
Area: studio
Yêu cầu: R2.3, R2.4, R3.2, R3.3, R4.4, WN5, WN11

## Mục tiêu

Mỗi Biểu thức kiểm kiểu tại vị trí bước, chỉ tham chiếu bước trội, và từ chối Trường người chạy không
đọc được; ba bước logic lát cần với mặc định đóng (workflow-nodes R2.3, R2.4, R3.2, R3.3, R4.4, WN5,
WN11).

## Việc cần làm

1. Môi trường biểu thức theo vị trí: `trigger`; mọi bước trội vị trí đó (dùng chung hàm dominator của
   `workflow-engine`, không bản sao); `bindings` (chỉ biến, không id kết nối); `run` (`id`, `mode`,
   `started_at`, `workflow`); `item`/`index` trong thân map. Không `now()`.
2. `GET /api/v1/studio/workflows/{id}/draft/scope?node=` (quyền `studio.workflows.edit`): cây biến có
   kiểu chỉ gồm bước trội, Trường đọc được với chủ thể chạy (dùng `visible_fields` của field-security).
3. Bộ kiểm phát hành (đưa vào bộ kiểm toàn đồ thị của workflow-engine): tham chiếu chưa khai hoặc không
   trội → `reference_not_dominating`; điều kiện không `bool` → `type_mismatch`; Trường người chạy không
   đọc được → `field_not_readable`; bảng ánh xạ kiểu dùng chung, keyed theo kiểu trường của
   custom-objects.
4. Ba loại bước: `data.transform` (tối đa 50 khoá), `logic.switch` (thành Đường nối có điều kiện, Nhánh
   ra mặc định bắt buộc), `flow.stop`. Hình chiếu `trigger.endpoint` ánh xạ payload vào `input_schema`
   bằng CEL, đánh giá ở ingress.
5. Mặc định đóng: một bước không khai Khi lỗi → `fail`; một `logic.switch` thiếu Nhánh ra mặc định →
   bộ kiểm phát hành từ chối.

## Tiêu chí chấp nhận

- [ ] R3.2: một Biểu thức tham chiếu một bước phía sau (không trội) → `reference_not_dominating`, không
      cho phát hành.
- [ ] R3.3: một điều kiện trả `string` → `type_mismatch`, không cho phát hành.
- [ ] R4.4 (WN5): tham chiếu `phone` không đọc được với chủ thể chạy → `field_not_readable` lúc phát
      hành và `field_hidden` lúc render; gỡ kiểm `visible_fields` → test đỏ.
- [ ] R2.3 (WN11): một bước không khai Khi lỗi biên dịch ra `fail`, không `continue`.
- [ ] R2.4 (WN11): một `logic.switch` thiếu Nhánh ra mặc định → bộ kiểm phát hành từ chối; thêm nhánh
      mặc định → qua.
- [ ] R3.2: cây `draft/scope` của một node chỉ liệt kê bước trội; bước phía sau không xuất hiện.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_variable_scope.py packages/python/dw_studio/tests/workflows/test_logic_nodes.py` xanh.

## Nguồn

- ADR-0114 (Proposed) quyết 3, 6; spec: R3.2, R3.3, R4.4.
- ADR-0112 (Proposed) quyết 3; spec: R2.4 (bộ kiểm toàn đồ thị).

## Comments
