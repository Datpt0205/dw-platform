# 10 — Bảng có trước luật của test phủ offboarding: xuất, xóa hay loại trừ đã kiểm

Status: needs-triage
Blocked by: 02, 08, 09
Area: studio
Yêu cầu: R11.16, FH43

## Mục tiêu

Test phủ offboarding hôm nay bỏ qua 25 bảng `platform` có trước luật (`_PLATFORM_PREDATING`), nên một bảng trong đó mà
lane không xóa không làm test nào đỏ (failure-modes #0). Ticket này cho mỗi bảng đó một cách mất dòng mà test phủ kiểm
theo catalog, sửa bảng nào thật sự bị bỏ lại, rồi gỡ danh sách (R11.16).

## Việc cần làm

1. Đo ở `902ac246a9dc` ngày 5/11/2026 (test phủ với danh sách rỗng, mọi schema), 9 bảng được nêu tên: không xóa
   `platform.approval_decision_codes` (`CASCADE` qua `platform.approval_view_receipts`, hai bậc từ
   `platform.approval_requests`), `platform.approval_view_receipts` (`CASCADE` từ `platform.approval_requests`),
   `platform.audit_events` (giữ theo fragment retention), `platform.channel_deliveries` và `platform.notifications`
   (`CASCADE` từ `platform.workspaces`), `platform.support_grants` (`CASCADE` từ `platform.workspaces`),
   `platform.sod_waivers` (chỉ `CASCADE` từ `platform.tenants`, bảng lane không xóa); không xuất và không xóa
   `platform.channel_preferences` (policy theo `app.principal_id`, không có policy `tenant_isolation_*`; `CASCADE` từ
   `platform.memberships`) và `platform.tenant_offboarding_requests` (`_NEVER_PURGE`).
2. Mỗi bảng có `CASCADE` một bậc từ bảng lane xóa: một dòng `OffboardingExclusion(cascade_from=...)`. Kiểm R4.4 của
   test phủ nhận chuỗi `CASCADE` nhiều bậc tới một bảng lane xóa, cho `platform.approval_decision_codes`.
3. `platform.audit_events`: dòng `kept` với term của `configs/policies/retention.d/platform.audit_events.yaml`.
4. `platform.sod_waivers`: một bước xóa của sổ (hàm SECURITY DEFINER như `platform.purge_tenant_service_users`, từ chối
   tenant không ở `offboarding`), migration mới; dòng của tenant B ở bảng này vào test FH35.
5. `platform.channel_preferences`: quyết định có vào gói xuất không (sở thích kênh của từng người, đọc theo người) và
   ghi ở Quyết định của spec; `platform.tenant_offboarding_requests`: dòng loại trừ nêu lý do của `_NEVER_PURGE`.
6. Gỡ `_PLATFORM_PREDATING` và kiểm R4.6 của nó khỏi `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py`.

## Tiêu chí chấp nhận

- [ ] R11.16 (FH43): không còn `_PLATFORM_PREDATING`, `test_offboarding_covers_every_table_it_has_to` vẫn `[]` trên
      checkout đã migrate; bỏ một dòng loại trừ vừa thêm → test nêu tên bảng đó; sai nếu test xanh khi thiếu dòng.
- [ ] R11.16 (FH43): purge tenant A khi A và B đều có dòng `platform.sod_waivers` → của A mất, của B còn; sai nếu dòng
      của A còn hay của B mất.
- [ ] Xong: `uv run pytest -m integration packages/python/dw_platform/tests/integration/test_offboarding.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py packages/python/dw_platform/tests/integration/test_privileges.py`
      xanh.

## Nguồn

- `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py:51-80`
- `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py:147-149`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:166`
- `db/migrations/versions/6b26771e549d_separation_of_duties_waivers_per_tenant.py:127-137`
- spec: R11.16, FH43; Quyết định 5/11/2026.

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): tách từ ticket 08 sau phép đo ở bước 1 (Quyết định 5/11/2026 của spec);
  `platform.sod_waivers` cần migration. Chưa gate.
