# 03 — Đọc grants_changed và giữ lượt chạy bằng binding_needs_review ở dispatch

Status: needs-triage
Blocked by: 02, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md
Area: studio
Yêu cầu: R3.6, R3.7, TR17

## Mục tiêu

Tài khoản dịch vụ được tăng quyền sau khi điểm gắn `principal` của nó được duyệt thì không chạy tiếp với tầm rộng
hơn người đã đề xuất: spec này đọc sự kiện outbox `platform.service_principal.grants_changed` mà org-and-principals
ghi, và kiểm `binding_needs_review` mà làn `studio_runs` hỏi ở dispatch giữ lượt chạy ở `queued` tới khi Bộ giá trị
gắn được đề xuất lại bởi người phủ đủ quyền và duyệt bởi người khác (R3.6, R3.7, TR17 của spec; V4.16;
ADR-0103 (Accepted) quyết 4).

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên, tạo bằng `alembic revision -m "..."`), chép nguyên văn mục Dữ liệu của
   spec: `studio.principal_grant_changes` với PK `(tenant_id, service_principal_id)`; `service_principal_id uuid NOT NULL`,
   FK ghép `(tenant_id, service_principal_id)` tới `platform.service_principals (tenant_id, user_id)` (UNIQUE
   `(tenant_id, user_id)` của org-and-principals/03) ON DELETE CASCADE, PK là index của nó; `grants_changed_at timestamptz NOT NULL`;
   `last_event_id uuid NOT NULL`; RLS ENABLE và FORCE chỉ theo tenant; `dw_app` SELECT, INSERT, UPDATE chỉ
   `grants_changed_at`, `last_event_id`, không DELETE, nên cùng thay đổi thêm một dòng `STUDIO_EXCLUSIONS` của
   studio-skeleton/01 cho bảng với lý do "`dw_app` không DELETE; xóa khi offboarding theo FK CASCADE từ
   `platform.service_principals`, mà cascade từ `platform.tenant_members`" (mục Dữ liệu của spec;
   studio-skeleton:R4.1); một dòng lý do trong danh sách bảng toàn tenant của
   `test_rls_coverage.py` (dấu thời điểm theo tài khoản dịch vụ, một chủ thể của cả công ty; DO-01); khẳng định
   grant trong `test_privileges.py`; `test_offboarding.py` purge một tenant có dòng ở bảng này, tenant khác nguyên;
   `dw_app` gắn tenant A chèn dòng mang `service_principal_id` của tài khoản dịch vụ tenant B → FK ghép từ chối.
2. Handler outbox cho `platform.service_principal.grants_changed` (payload `tenant_id`, `service_principal_id` của
   org-and-principals/03), đăng ký ở composition root của worker (`apps/worker/src/dw_worker/main.py`): trong giao
   dịch của lần giao sự kiện, đặt `app.tenant_id` theo `set_config(..., true)` từ `tenant_id` của sự kiện, rồi upsert một
   dòng với `grants_changed_at` là `greatest` của giá trị đang có và thời điểm ghi của sự kiện, `last_event_id` là id
   sự kiện; giao lại cùng sự kiện → không đổi dòng nào (R3.6).
3. Kiểm `binding_needs_review` (R3.7; V4.16): một adapter đáp ứng `BindingReviewPort` mà workflow-engine/04 khai và
   làn `studio_runs` hỏi ở dispatch cho lượt `datahub`, `provider_app`, `record_event` (workflow-engine:R5.19), nối ở
   composition root của worker: khi dòng của tài khoản dịch vụ `run_as_principal_id` của lượt trong
   `studio.principal_grant_changes` có `grants_changed_at` muộn hơn `decided_at` của lần duyệt gần nhất của một Bộ giá
   trị gắn `approved` của thành phần mang chính tài khoản đó ở điểm gắn `principal` (tenant-config/05) → trả giữ kèm
   `grants_changed_at`, để làn giữ lượt ở `queued`, không node nào chạy, và báo người giữ `studio.bindings.approve`
   (workflow-engine:R5.21). Kiểm không so với Bộ giá trị gắn mà lượt ghim, vì lượt đang giữ ghim bộ được duyệt trước
   lần tăng quyền; lượt vẫn chạy với Bộ giá trị gắn đã ghim (tenant-config:R7.5). Kiểm không còn đăng ký vào bộ kiểu
   Điểm gắn của tenant-config/05 lúc ghim, nên lượt được xin như mọi lượt và lần kích hoạt ghi `run_requested`.
4. Người phủ đủ quyền mới (kiểm `grants_cover` lúc đề xuất của ticket 01) đề xuất lại Bộ giá trị gắn và một người
   khác duyệt: `decided_at` mới muộn hơn `grants_changed_at`, nên ở chu kỳ kế tiếp port thôi báo giữ và làn nhận các
   lượt đang giữ theo thứ tự `available_at`; duyệt lại với một tài khoản dịch vụ khác không nhả lượt của tài khoản cũ;
   không cần xóa dòng nào.

## Tiêu chí chấp nhận

- [ ] R3.6 (TR17): tăng quyền một tài khoản dịch vụ → handler ghi một dòng với `grants_changed_at` và `last_event_id`
      của sự kiện; outbox giao lại cùng sự kiện → dòng không đổi; sự kiện cũ hơn tới sau → `grants_changed_at` không
      lùi; dòng gắn tenant A mang `service_principal_id` của tài khoản dịch vụ tenant B → FK ghép từ chối, không dòng
      nào được ghi; đổi FK đó về FK một cột `service_principal_id` → ca đó qua, test đỏ.
- [ ] R3.6: công ty `offboarding` có dòng `studio.principal_grant_changes` → lane `offboarding` xuất mỗi dòng một
      lần, rồi lượt xóa `platform.tenant_members` của công ty xóa hết các dòng đó qua cascade từ
      `platform.service_principals`, dòng của công ty khác còn nguyên; test phủ offboarding (studio-skeleton:R4.1)
      xanh với dòng `STUDIO_EXCLUSIONS` của bảng, bỏ dòng đó → test phủ đỏ, nêu tên bảng; đổi FK
      `service_principal_id` sang `RESTRICT` → lượt xóa lỗi, test đỏ.
- [ ] R3.7 (TR17): tăng quyền tài khoản dịch vụ sau khi Bộ giá trị gắn được duyệt, rồi gửi hai sự kiện có chữ ký tới
      Nguồn dữ liệu → hai lần kích hoạt `run_requested`, hai lượt chạy giữ `queued`, không node nào chạy; đề xuất lại
      bởi người phủ đủ quyền và duyệt bởi người khác với cùng tài khoản → hai lượt chạy theo thứ tự đến; duyệt lại với
      một tài khoản dịch vụ khác → hai lượt vẫn giữ; so `grants_changed_at` với Bộ giá trị gắn mà lượt ghim → hai lượt
      giữ mãi sau khi duyệt lại, test đỏ; gỡ kiểm → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `.claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md` (trigger AFTER ghi outbox
  `platform.service_principal.grants_changed`); org-and-principals:R6.6; spec: R3.6, R3.7, TR17.
- workflow-engine/04 (`BindingReviewPort`, hàng `binding_needs_review` ở dispatch; workflow-engine:R5.19, R5.21);
  tenant-config/05 (Bộ giá trị gắn và `decided_at` của lần duyệt; tenant-config:R7.5); ADR-0103 (Accepted) quyết 4.

## Comments

- 2026-10-24 (agent): ticket mới theo quyết định của Đạt ngày 24/10/2026 (H:org-and-principals:R6.6~workflow-triggers:R3.4):
  sự kiện `grants_changed` có người đọc ở W1, nên tài khoản dịch vụ tăng quyền sau khi gắn dừng ở cửa nhận.
- 2026-10-24 (agent): kiểm sau vòng sửa thứ tư, sửa ở lượt b: khóa ngoại `service_principal_id` thành FK ghép
  `(tenant_id, service_principal_id)` tới UNIQUE `(tenant_id, user_id)` của `platform.service_principals`, để cơ sở dữ
  liệu chặn tham chiếu chéo tenant, và khóa chính là index của nó, nên index riêng `(service_principal_id)` mà lượt a
  thêm bỏ (CLAUDE.md, Data model rules; phát hiện E về CLAUDE.md và Dữ liệu của spec).
- 2026-10-24 (agent): lượt d của vòng 4: dòng Comments của lượt b thôi dẫn mã mục của lượt, nội dung giữ nguyên.
- 2026-10-24 (agent): `studio.principal_grant_changes` không có DELETE cho `dw_app`, nên bước 1 thêm một dòng
  `STUDIO_EXCLUSIONS` nêu cách xóa theo cascade từ `platform.service_principals`, và tiêu chí R3.6 thêm ca offboarding
  cùng ca bỏ dòng đó (studio-skeleton:R4.1; CLAUDE.md, Data model rules). Không thêm cạnh: ticket này chờ
  org-and-principals/03, nơi FK cascade của `platform.service_principals` ra đời, và chờ studio-skeleton/01 qua
  org-and-principals/02.
- 2026-10-24 (agent): ca chéo tenant của FK ghép `service_principal_id` ở tiêu chí R3.6 (TR17) thêm "không dòng nào
  được ghi" và một test đột biến đổi FK đó về FK một cột, như ca của mọi FK ghép khác của spec ở ticket 01 và 02
  (CLAUDE.md, Tenancy and authorization; failure-modes #3). Không thêm cạnh.
- 2026-10-24 (agent): theo V4.16 của Đạt, `binding_needs_review` giữ lượt chạy ở `queued` thay vì từ chối: kiểm rời bộ
  kiểu Điểm gắn của tenant-config/05 sang adapter của `BindingReviewPort` mà làn `studio_runs` hỏi ở mỗi lần nhận, so
  với lần duyệt gần nhất mang chính tài khoản đó, nên lượt đang giữ được nhả khi Bộ giá trị gắn được duyệt lại (bước 3,
  4, tiêu chí R3.7); lần kích hoạt ghi `run_requested`; lời báo người giữ `studio.bindings.approve` là của làn
  (workflow-engine:R5.21); tiêu đề đổi "dừng" thành "giữ". Không thêm cạnh: ticket này chờ workflow-engine/04, nơi
  port được khai, qua ticket 02 và 01.
- 2026-10-24 (agent): kiểm lượt f của vòng 4: tiêu đề, và dòng của ticket ở Danh sách ticket của spec, đổi "ở cửa
  nhận" thành "ở dispatch", vì từ V4.16 kiểm `binding_needs_review` chạy ở dispatch của làn `studio_runs`
  (workflow-engine:R5.19), không ở cửa nhận lượt chạy, như Mục tiêu, bước 3 và R3.7 đã ghi. Không thêm cạnh.
