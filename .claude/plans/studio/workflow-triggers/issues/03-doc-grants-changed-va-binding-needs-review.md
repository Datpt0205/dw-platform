# 03 — Đọc grants_changed và dừng lượt chạy bằng binding_needs_review ở cửa nhận

Status: needs-triage
Blocked by: 02, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md
Area: studio
Yêu cầu: R3.6, R3.7, TR17

## Mục tiêu

Tài khoản dịch vụ được tăng quyền sau khi điểm gắn `principal` của nó được duyệt thì không chạy tiếp với tầm rộng
hơn người đã đề xuất: spec này đọc sự kiện outbox `platform.service_principal.grants_changed` mà org-and-principals
ghi, và cửa nhận lượt chạy từ chối `binding_needs_review` tới khi Bộ giá trị gắn được đề xuất lại bởi người phủ đủ
quyền và duyệt bởi người khác (R3.6, R3.7, TR17 của spec; ADR-0103 (Accepted) quyết 4).

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên, tạo bằng `alembic revision -m "..."`), chép nguyên văn mục Dữ liệu của
   spec: `studio.principal_grant_changes` với PK `(tenant_id, service_principal_id)`; `service_principal_id uuid NOT NULL`,
   FK ghép `(tenant_id, service_principal_id)` tới `platform.service_principals (tenant_id, user_id)` (UNIQUE
   `(tenant_id, user_id)` của org-and-principals/03) ON DELETE CASCADE, PK là index của nó; `grants_changed_at timestamptz NOT NULL`;
   `last_event_id uuid NOT NULL`; RLS ENABLE và FORCE chỉ theo tenant; `dw_app` SELECT, INSERT, UPDATE chỉ
   `grants_changed_at`, `last_event_id`, không DELETE; một dòng lý do trong danh sách bảng toàn tenant của
   `test_rls_coverage.py` (dấu thời điểm theo tài khoản dịch vụ, một chủ thể của cả công ty; DO-01); khẳng định
   grant trong `test_privileges.py`; `test_offboarding.py` purge một tenant có dòng ở bảng này, tenant khác nguyên;
   `dw_app` gắn tenant A chèn dòng mang `service_principal_id` của tài khoản dịch vụ tenant B → FK ghép từ chối.
2. Handler outbox cho `platform.service_principal.grants_changed` (payload `tenant_id`, `service_principal_id` của
   org-and-principals/03), đăng ký ở composition root của worker (`apps/worker/src/dw_worker/main.py`): trong giao
   dịch của lần giao sự kiện, đặt `app.tenant_id` theo `set_config(..., true)` từ `tenant_id` của sự kiện, rồi upsert một
   dòng với `grants_changed_at` là `greatest` của giá trị đang có và thời điểm ghi của sự kiện, `last_event_id` là id
   sự kiện; giao lại cùng sự kiện → không đổi dòng nào (R3.6).
3. Kiểm lúc nhận lượt chạy của kind `principal`, đăng ký vào bộ kiểu Điểm gắn của tenant-config/05 (bước 9 của ticket
   đó gọi nó lúc ghim điểm gắn): với điểm gắn `principal` dùng làm danh tính chạy, khi dòng của tài khoản dịch vụ
   trong `studio.principal_grant_changes` có `grants_changed_at` muộn hơn `decided_at` của Bộ giá trị gắn `approved` mà
   lượt chạy ghim → từ chối nhận với `binding_needs_review`, không dòng `platform.worker_runs` nào được tạo, không node
   nào chạy (R3.7). Làn `studio_inbound` ghi lần kích hoạt `rejected` cho sự kiện bị từ chối như vậy.
4. Người phủ đủ quyền mới (kiểm `grants_cover` lúc đề xuất của ticket 01) đề xuất lại Bộ giá trị gắn và một người
   khác duyệt: `decided_at` mới muộn hơn `grants_changed_at`, nên lượt chạy kế tiếp được nhận; không cần xóa dòng nào.

## Tiêu chí chấp nhận

- [ ] R3.6 (TR17): tăng quyền một tài khoản dịch vụ → handler ghi một dòng với `grants_changed_at` và `last_event_id`
      của sự kiện; outbox giao lại cùng sự kiện → dòng không đổi; sự kiện cũ hơn tới sau → `grants_changed_at` không
      lùi; dòng gắn tenant A mang `service_principal_id` của tài khoản dịch vụ tenant B → FK ghép từ chối.
- [ ] R3.7 (TR17): tăng quyền tài khoản dịch vụ sau khi Bộ giá trị gắn được duyệt, rồi gửi một sự kiện có chữ ký tới
      Nguồn dữ liệu → lần kích hoạt `rejected` với `binding_needs_review`, không lượt chạy nào; đề xuất lại bởi người
      phủ đủ quyền và duyệt bởi người khác, rồi gửi sự kiện kế tiếp → một lượt chạy được xin; gỡ kiểm lúc nhận của kind
      `principal` → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `.claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md` (trigger AFTER ghi outbox
  `platform.service_principal.grants_changed`); org-and-principals:R6.6; spec: R3.6, R3.7, TR17.
- tenant-config/05 (bộ kiểu Điểm gắn, kiểm lúc nhận lượt chạy ở bước 9); ADR-0103 (Accepted) quyết 4.

## Comments

- 2026-10-24 (agent): ticket mới theo quyết định của Đạt ngày 24/10/2026 (H:org-and-principals:R6.6~workflow-triggers:R3.4):
  sự kiện `grants_changed` có người đọc ở W1, nên tài khoản dịch vụ tăng quyền sau khi gắn dừng ở cửa nhận.
- 2026-10-24 (agent): kiểm sau vòng sửa thứ tư, sửa ở lượt b: khóa ngoại `service_principal_id` thành FK ghép
  `(tenant_id, service_principal_id)` tới UNIQUE `(tenant_id, user_id)` của `platform.service_principals`, để cơ sở dữ
  liệu chặn tham chiếu chéo tenant, và khóa chính là index của nó, nên index riêng `(service_principal_id)` mà lượt a
  thêm bỏ (B14; CLAUDE.md, Data model rules; phát hiện E về CLAUDE.md và Dữ liệu của spec).
