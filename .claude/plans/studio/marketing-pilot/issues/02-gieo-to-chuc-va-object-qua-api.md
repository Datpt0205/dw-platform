# 02 — Tenant thí điểm, hai workspace, vai và object dựng qua API

Status: needs-triage
Blocked by: .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md, .claude/plans/studio/tenant-rbac/issues/03-chong-leo-thang-va-api-quan-tri-vai.md, .claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/record-access/issues/03-policy-ban-ghi-va-mac-dinh-truy-cap.md, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4

## Mục tiêu

Người đặt yêu cầu cần một bộ cố định hai công ty cô lập dựng chỉ qua API công khai, làm nền cho mọi ticket sau và làm nguồn của Gói Marketing 1.0 ở W2 (marketing-pilot R1.1, R1.2, R1.3, R1.4). Gộp B12-product marketing-pilot 05 và 06; không có bộ cài gói ở W1.

## Việc cần làm

1. Script gieo ở harness của lát (`tests/e2e/marketing_pilot/seed.py`) gọi chỉ các route API công khai của Studio qua một client HTTP: tạo công ty A (demo) và công ty B (đối chứng), mỗi công ty hai workspace Marketing và Sales dưới workspace gốc; không gọi adapter, không SQL, không migration.
2. Qua `POST /api/v1/studio/objects` phát hành `mkt_lead` và `mkt_campaign` cho mỗi công ty theo mục Dữ liệu của spec: mọi trường khai `pd_category`; `phone_e164` và `email` ở chế độ bảo vệ; mặc định truy cập `private`; `phone_e164` là trường duy nhất (custom-objects:R1.2, R2.2). Dùng ticket `.claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md`.
3. Qua API quản trị vai trò tạo vai Marketing, Sales, trưởng Marketing và Cộng tác viên Marketing với độ sâu (Sales đọc Lead mức Của tôi; trưởng Marketing mức Workspace của tôi và cấp dưới), và quyền trường `phone_e164`/`email` cấp cho vai cần nhưng không cấp cho Cộng tác viên Marketing (tenant-rbac:R9.1). Dùng `.claude/plans/studio/tenant-rbac/issues/03-chong-leo-thang-va-api-quan-tri-vai.md` và `.claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md` và `.claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md`.
4. Qua API tạo một tài khoản dịch vụ cho quy trình, cấp đúng quyền cần (đọc/ghi `mkt_lead`, đọc `mkt_campaign`), để ticket 03 gắn làm chủ thể chạy không người kích hoạt (org-and-principals:R6.1). Dùng `.claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md`.
5. Mặc định truy cập `private` và các lớp quyền bản ghi để công ty B không thấy gì của công ty A (record-access:R2.1). Dùng `.claude/plans/studio/record-access/issues/03-policy-ban-ghi-va-mac-dinh-truy-cap.md`.
6. Một ràng buộc độc lập import-linter trong `pyproject.toml` gốc (`marketing_pilot_independence`) cấm `tests/e2e/marketing_pilot/*` import bất kỳ `dw_*.adapters*` hay nội bộ nền tảng; harness chỉ dùng client HTTP công khai.

## Tiêu chí chấp nhận

- [ ] R1.1: chạy `seed.py` dựng hai công ty, bốn workspace, hai đối tượng mỗi công ty, bốn vai (gồm Cộng tác viên Marketing thiếu quyền trường) và một tài khoản dịch vụ, chỉ bằng lời gọi HTTP tới route công khai; không lời gọi nào chạm database trực tiếp.
- [ ] R1.2: thêm một `import` adapter vào `tests/e2e/marketing_pilot/` làm `lint-imports` (import-linter) đỏ; đó là test âm của MP17.
- [ ] R1.3: người của công ty B gọi `GET`/`POST .../objects/mkt_lead/records` của công ty A trả 404 hoặc 0 dòng; đọc thẳng partition của công ty A trả 0 dòng (custom-objects:R4.2, R4.3; record-access:R4.2, R4.3).
- [ ] R1.4: describe `mkt_lead` và `mkt_campaign` cho thấy mọi trường có `pd_category` và `default_access = private`; bỏ `pd_category` một trường làm phát hành đối tượng trả 422 `pd_category_required`.
- [ ] Xong: `uv run pytest tests/e2e/marketing_pilot/test_seed.py` xanh.

## Nguồn

- spec: R1.1, R1.2, R1.3, R1.4.
- custom-objects:R1.2, R2.2, R4.2, R4.3; record-access:R2.1, R4.2, R4.3; tenant-rbac:R9.1; org-and-principals:R6.1; YC2, YC3; ADR-0100 (Proposed).

## Comments
